/*-
 * Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <sys/select.h>
#include <sys/socket.h>

#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "orch.h"
#include "orch_lib.h"

struct orch_ipc_header {
	size_t			 size;
	enum orch_ipc_tag	 tag;
};

struct orch_ipc_msg {
	struct orch_ipc_header		 hdr;
	/* Non-wire contents between hdr and data */
	_Alignas(max_align_t) unsigned char	 data[];
};

/*
 * We'll start making a distinction between things that need the size of an
 * orch_ipc_msg and things that need the size we would see on the wire.  The
 * header contains the latter, but the orch_ipc_msg may have more contents that
 * are used for internal book-keeping.
 */
#define	IPC_MSG_SIZE(payloadsz)	\
	(sizeof(struct orch_ipc_msg) + payloadsz)
#define	IPC_MSG_HDR_SIZE(payloadsz)	\
	(sizeof(struct orch_ipc_header) + payloadsz)

#define	IPC_MSG_PAYLOAD_SIZE(msg)	\
	((msg)->hdr.size - sizeof(msg->hdr))

struct orch_ipc_msgq {
	struct orch_ipc_msg	*msg;
	struct orch_ipc_msgq	*next;
};

struct orch_ipc_register {
	orch_ipc_handler	*handler;
	void			*cookie;
};

struct orch_ipc {
	struct orch_ipc_register	 callbacks[IPC_LAST - 1];
	struct orch_ipc_msgq		*head;
	struct orch_ipc_msgq		*tail;
	int				 sockfd;
};

static int orch_ipc_drain(orch_ipc_t);
static int orch_ipc_pop(orch_ipc_t, struct orch_ipc_msg **);
static int orch_ipc_poll(orch_ipc_t, bool *);

int
orch_ipc_close(orch_ipc_t ipc)
{
	int error;

	if (ipc == NULL)
		return (0);

	error = 0;
	if (ipc->sockfd != -1) {
		shutdown(ipc->sockfd, SHUT_WR);

		/*
		 * orch_ipc_drain() should hit EOF then close the socket.  This
		 * will just drain the socket, a follow-up orch_ipc_pop() will
		 * drain the read queue and invoke callbacks.
		 */
		while (ipc->sockfd != -1 && error == 0) {
			orch_ipc_wait(ipc, NULL);

			error = orch_ipc_drain(ipc);
		}

		if (ipc->sockfd != -1) {
			close(ipc->sockfd);
			ipc->sockfd = -1;
		}
	}

	/*
	 * We may have hit EOF at an inopportune time, just cope with it
	 * and free the queue.
	 */
	error = orch_ipc_pop(ipc, NULL);
	assert(ipc->head == NULL);

	free(ipc);

	return (error);
}

orch_ipc_t
orch_ipc_open(int fd)
{
	orch_ipc_t hdl;

	hdl = malloc(sizeof(*hdl));
	if (hdl == NULL)
		return (NULL);

	memset(&hdl->callbacks[0], 0, sizeof(hdl->callbacks));
	hdl->head = hdl->tail = NULL;
	hdl->sockfd = fd;
	return (hdl);
}

bool
orch_ipc_okay(orch_ipc_t ipc)
{

	return (ipc->sockfd >= 0);
}

struct orch_ipc_msg *
orch_ipc_msg_alloc(enum orch_ipc_tag tag, size_t payloadsz, void **payload)
{
	struct orch_ipc_msg *msg;
	size_t msgsz;

	assert(payloadsz >= 0);
	assert(payloadsz == 0 || payload != NULL);
	assert(tag != IPC_NOXMIT);

	msg = calloc(1, IPC_MSG_SIZE(payloadsz));
	if (msg == NULL)
		return (NULL);

	msg->hdr.tag = tag;
	msg->hdr.size = IPC_MSG_HDR_SIZE(payloadsz);

	if (payloadsz != 0)
		*payload = msg + 1;

	return (msg);
}

void *
orch_ipc_msg_payload(struct orch_ipc_msg *msg, size_t *odatasz)
{
	size_t datasz = IPC_MSG_PAYLOAD_SIZE(msg);

	/*
	 * orch_ipc_drain() should have rejected negative payload indications.
	 */
	assert(datasz >= 0);
	if (odatasz != NULL)
		*odatasz = datasz;
	if (datasz == 0)
		return (NULL);
	return (msg + 1);
}

enum orch_ipc_tag
orch_ipc_msg_tag(struct orch_ipc_msg *msg)
{

	return (msg->hdr.tag);
}

void
orch_ipc_msg_free(struct orch_ipc_msg *msg)
{

	free(msg);
}

static int
orch_ipc_drain(orch_ipc_t ipc)
{
	struct orch_ipc_header hdr;
	struct orch_ipc_msg *msg;
	struct orch_ipc_msgq *msgq;
	ssize_t readsz;
	size_t off, resid;

	if (!orch_ipc_okay(ipc))
		return (0);

	for (;;) {
		readsz = read(ipc->sockfd, &hdr, sizeof(hdr));
		if (readsz == -1) {
			if (errno == EAGAIN)
				break;
			return (-1);
		} else if (readsz == 0) {
			goto eof;
		}

		/*
		 * We might have an empty payload, but we should never have less
		 * than a header's worth of data.
		 */
		if (hdr.size < sizeof(hdr) || hdr.tag == IPC_NOXMIT) {
			errno = EINVAL;
			return (-1);
		}

		msg = malloc(IPC_MSG_SIZE(hdr.size));
		if (msg == NULL)
			return (-1);

		msgq = malloc(sizeof(*msgq));
		if (msgq == NULL) {
			free(msg);
			errno = ENOMEM;
			return (-1);
		}

		msgq->msg = msg;
		msgq->next = NULL;

		msg->hdr = hdr;

		off = 0;
		resid = IPC_MSG_PAYLOAD_SIZE(msg);

		while (resid != 0) {
			readsz = read(ipc->sockfd, &msg->data[off], resid);
			if (readsz == -1) {
				if (errno != EAGAIN) {
					free(msg);
					return (-1);
				}

				if (orch_ipc_poll(ipc, NULL) == -1) {
					free(msg);
					return (-1);
				}

				continue;
			} else if (readsz == 0) {
				free(msg);
				msg = NULL;

				goto eof;
			}

			off += readsz;
			resid -= readsz;
		}

		if (ipc->head == NULL) {
			ipc->head = ipc->tail = msgq;
		} else {
			ipc->tail->next = msgq;
			ipc->tail = msgq;
		}

		msg = NULL;
		msgq = NULL;
	}

	return (0);
eof:

	assert(ipc->sockfd >= 0);
	close(ipc->sockfd);
	ipc->sockfd = -1;

	return (0);
}

static int
orch_ipc_pop(orch_ipc_t ipc, struct orch_ipc_msg **omsg)
{
	struct orch_ipc_register *reg;
	struct orch_ipc_msgq *msgq;
	struct orch_ipc_msg *msg;
	int error;

	error = 0;
	while (ipc->head != NULL) {
		/* Dequeue a msg */
		msgq = ipc->head;
		ipc->head = ipc->head->next;

		/* Free the container */
		msg = msgq->msg;

		free(msgq);
		msgq = NULL;

		/* Do we have a handler for it? */
		reg = &ipc->callbacks[msg->hdr.tag - 1];
		if (reg->handler != NULL) {
			int serr;

			error = (*reg->handler)(ipc, msg, reg->cookie);
			if (error != 0)
				serr = errno;

			free(msg);
			msg = NULL;

			if (error != 0) {
				errno = serr;
				error = -1;
				break;
			}

			/*
			 * Try to dequeue another one... the handler is allowed
			 * to shut down IPC, so let's be careful here.
			 */
			continue;
		}

		/*
		 * No handler, potentially tap this one out.  If we don't have
		 * an omsg, we're just draining so we'll free the msg here.
		 */
		if (omsg == NULL) {
			free(msg);
			msg = NULL;

			continue;
		}

		*omsg = msg;
		break;
	}

	return (error);
}

int
orch_ipc_recv(orch_ipc_t ipc, struct orch_ipc_msg **omsg)
{
	struct orch_ipc_msg *rcvmsg;
	int error;

	if (orch_ipc_drain(ipc) != 0)
		return (-1);

	rcvmsg = NULL;
	error = orch_ipc_pop(ipc, &rcvmsg);
	if (error == 0)
		*omsg = rcvmsg;
	return (error);
}

int
orch_ipc_register(orch_ipc_t ipc, enum orch_ipc_tag tag,
    orch_ipc_handler *handler, void *cookie)
{
	struct orch_ipc_register *reg = &ipc->callbacks[tag - 1];

	reg->handler = handler;
	reg->cookie = cookie;
	return (0);
}

int
orch_ipc_send(orch_ipc_t ipc, struct orch_ipc_msg *msg)
{
	ssize_t writesz;
	size_t off, resid;

retry:
	if (orch_ipc_drain(ipc) != 0)
		return (-1);

	writesz = write(ipc->sockfd, &msg->hdr, sizeof(msg->hdr));
	if (writesz == -1) {
		if (errno != EAGAIN)
			return (-1);
		goto retry;
	} else if ((size_t)writesz < sizeof(msg->hdr)) {
		errno = EIO;
		return (-1);
	}

	off = 0;
	resid = IPC_MSG_PAYLOAD_SIZE(msg);
	while (resid != 0) {
		writesz = write(ipc->sockfd, &msg->data[off], resid);
		if (writesz == -1) {
			if (errno != EAGAIN)
				return (-1);
			continue;
		}

		off += writesz;
		resid -= writesz;
	}

	return (0);
}

int
orch_ipc_send_nodata(orch_ipc_t ipc, enum orch_ipc_tag tag)
{
	struct orch_ipc_msg msg = { 0 };

	msg.hdr.tag = tag;
	msg.hdr.size = IPC_MSG_HDR_SIZE(0);

	return (orch_ipc_send(ipc, &msg));
}

static int
orch_ipc_poll(orch_ipc_t ipc, bool *eof_seen)
{
	fd_set rfd;
	int error;

	if (eof_seen != NULL)
		*eof_seen = false;

	FD_ZERO(&rfd);
	do {
		if (ipc->sockfd == -1) {
			if (eof_seen != NULL)
				*eof_seen = true;
			return (0);
		}

		FD_SET(ipc->sockfd, &rfd);

		error = select(ipc->sockfd + 1, &rfd, NULL, NULL, NULL);
	} while (error == -1 && errno == EINTR);

	return (error);
}

int
orch_ipc_wait(orch_ipc_t ipc, bool *eof_seen)
{

	/*
	 * If we have any messages in the queue, don't bother polling; recv
	 * will return something.
	 */
	if (ipc->head != NULL)
		return (0);

	return (orch_ipc_poll(ipc, eof_seen));
}
