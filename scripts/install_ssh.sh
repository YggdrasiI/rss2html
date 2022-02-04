#!/bin/bash
#
# Creates ssh-key and updates target system
# by entry in {remote system}/.ssh/authorized_keys.
#
# This entry is prepended by command="...." to restrict access
# on this script only. (Well, unless a new ENVVARS-bug is found…)
# 
# Combine it with entry in .ssh/authorized_keys file:
# command="[path to script]/rss2html_ssh.sh" [SSH KEY]

SSHDIR="$HOME/.ssh"
KEYFILE="rss2html"
RSS2HTML_SCRIPT="rss2html_ssh.sh"
TMPDIR="/tmp"

setup_files () {
	if [ -f "${SSHDIR}/${KEYFILE}" -a -f "${SSHDIR}/${KEYFILE}.pub" ] ;
	then
		if [ ! -f "${SSHDIR}/${KEYFILE}" -o ! -f "${SSHDIR}/${KEYFILE}.pub" ] ;
		then
			echo "Hey, one of the keyfile exists but not both?!"
			exit -1
		fi
		echo "Key already generated."
	else
		ssh-keygen -f "${SSHDIR}/${KEYFILE}" -P ""
	fi

	if [ ! -f "${SSHDIR}/${KEYFILE}" -o ! -f "${SSHDIR}/${KEYFILE}.pub" ] ;
	then 
		echo "Generation of keyfile failed."
		exit -1
	fi

	PUBKEY=$(cat "${SSHDIR}/${KEYFILE}.pub")
	CMD_AND_PUBKEY="command=\"./.ssh/${RSS2HTML_SCRIPT}\" $PUBKEY"
	echo "${CMD_AND_PUBKEY}" > "${TMPDIR}/${KEYFILE}.cmd"

	if [ -f "${RSS2HTML_SCRIPT}" ] ; then
		SCRIPTFILE="${RSS2HTML_SCRIPT}"
	else
		echo "Copy example file"
		SCRIPTFILE="${RSS2HTML_SCRIPT}.example"
	fi

	cp "${SCRIPTFILE}" "${TMPDIR}/${RSS2HTML_SCRIPT}"
}

transfer_files() {
	echo "Copy ${RSS2HTML_SCRIPT} to target system"

	scp "${TMPDIR}/${RSS2HTML_SCRIPT}" "${TMPDIR}/${KEYFILE}.cmd" \
		"${SSH_TARGET}:.ssh/."
	ssh "${SSH_TARGET}" \
		"test \"\$(cat \"\${HOME}/.ssh/${KEYFILE}.cmd\")\" = \"\$(tail -n1 \"\${HOME}/.ssh/authorized_keys\")\" ||" \
		"cat \"\${HOME}/.ssh/${KEYFILE}.cmd\" >> \"\${HOME}/.ssh/authorized_keys\""

}

cleanup() {
	rm "${TMPDIR}/${RSS2HTML_SCRIPT}" "${TMPDIR}/${KEYFILE}.cmd"
}

test_connection() {
	RET=$(ssh "${SSH_TARGET}" -i "${SSHDIR}/${KEYFILE}" 'PING')
	if [ "$RET" = "PONG" ] ; then
		echo "Script successful installed!"
	else
		echo "Pinging script failed. Server replies: '$RET'"
	fi
}

print_settings_change () {
	ACTION_TEMPLATE="$(cat <<-EOF
		ssh_args = ("%s", "%s '{url}'", "~/.ssh/rss2html")
		ACTIONS.update({
		    "play_ssh" : { 
		        "handler": actions.factory__ssh_cmd(*ssh_args),
		        "check": actions.can_play,
		        "title": _('SSH Play'),
		        "icon": "icons/gnome_term.png",
		    },
		})
EOF
)"

printf -v SETTINGS_PLAY "$ACTION_TEMPLATE" "$SSH_TARGET" "PLAY"

echo "Add following to your settings.py to enable 'PLAY' target on remote machine:"
echo -e "\n${SETTINGS_PLAY}\n\n"
}

usage() {
	echo "Transfer and enable \"${RSS2HTML_SCRIPT}\" on remote machine.\n"
	echo -e "Usage:\n\t$0 \"user@machine\""
}

if [ "$#" -lt 1 ] ; then
	usage 
	exit -1
fi

SSH_TARGET="$1"

setup_files
transfer_files
test_connection

print_settings_change

cleanup
echo "Done"
