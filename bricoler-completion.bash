#
# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#

_bricoler_completions()
{
    local cmd completes cur params prev subcmds tasks

    cmd=$1
    subcmds="list run"
    tasks=$("$cmd" list 2>/dev/null)

    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD - 1]}"
    # Magic to ensure that <task>:<param>=<value> can be completed as I want.
    # bash includes ":" in COMP_WORDBREAKS, so this doesn't work otherwise.
    _get_comp_words_by_ref -n ':=' cur prev

    if [ $COMP_CWORD -eq 1 ]; then
        # Complete the verb.
        COMPREPLY=($(compgen -W "$subcmds" -- "$cur"))
        return 0
    fi

    params=""
    if [ $COMP_CWORD -ge 2 -a ${COMP_WORDS[1]} = "run" ]; then
        # Assume that the argument following "run" is the task name.
        # This doesn't have to be true, maybe we should try harder...
        params=$("$cmd" list ${COMP_WORDS[2]} 2>/dev/null | awk '{print $1"="}')
        options="--show --param --workdir"
    fi

    case $prev in
    -p|--param)
        compopt -o nospace
        COMPREPLY=($(compgen -W "$params" -- "$cur"))
        # Complements the _get_comp_words_by_ref magic above.
        __ltrim_colon_completions "$cur"
        return 0
        ;;
    -w|--workdir)
        COMPREPLY=($(compgen -d -- "$cur"))
        return 0
        ;;
    run)
        COMPREPLY=($(compgen -W "$tasks" -- "$cur"))
        return 0
        ;;
    *)
        COMPREPLY=($(compgen -W "$options" -- "$cur"))
        return 0
        ;;
    esac
}

complete -F _bricoler_completions bricoler
