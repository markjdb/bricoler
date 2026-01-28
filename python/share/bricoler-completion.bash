#
# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#

_bricoler_completions()
{
    local all_opts cmd cur params prev task tasks

    cmd=$1
    options="--skip --show --list --workdir"
    tasks=$(BRICOLER_ARGCOMPLETE=1 "$cmd" -l 2>/dev/null)

    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD - 1]}"

    # Do all options so far start with "-"?
    all_opts=1
    for word in "${COMP_WORDS[@]:1}"; do
        case "$word" in
        -*|$cur)
            ;;
        *)
            all_opts=0
            task="$word"
            params=$(BRICOLER_ARGCOMPLETE=1 "$cmd" $task -l 2>/dev/null)
            break
            ;;
        esac
    done

    if [ $all_opts -eq 1 ]; then
        COMPREPLY=($(compgen -W "$tasks" -- "$cur"))
        return 0
    else
        compopt -o nospace
        COMPREPLY=($(compgen -W "$params" -- "$cur"))
        return 0
    fi

    params=""
    if [ "$COMP_CWORD" -ge 2 -a "${COMP_WORDS[1]}" = "run" ]; then
        # Assume that the argument following "run" is the task name.
        # This doesn't have to be true, maybe we should try harder...
        params=$(BRICOLER_ARGCOMPLETE=1 "$cmd" -l ${COMP_WORDS[2]} 2>/dev/null)
    fi

    case $prev in
    -w|--workdir)
        COMPREPLY=($(compgen -d -- "$cur"))
        return 0
        ;;
    *)
        COMPREPLY=($(compgen -W "$options" -- "$cur"))
        return 0
        ;;
    esac
}

complete -F _bricoler_completions bricoler
