#!/usr/bin/env bash
# Tear the rendezvous lane down: the instance and the group it made. Found by
# tag rather than by state/, so a run whose state was lost is still cleaned
# up. Ends with status.sh, which must print nothing that bills.
#
# The key pair stays: the other lanes of this harness share it. The network
# name and secret in state/easytier_network stay too, because the only copy
# of a secret is not a teardown's to decide about; delete the file by hand and
# the next up.sh mints a new network.

source "$(dirname "$0")/lane.sh"

echo "== instance"
IDS="$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$ET_NAME" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
if [ -n "$IDS" ]; then
    # shellcheck disable=SC2086
    aws ec2 terminate-instances --instance-ids $IDS \
        --query 'TerminatingInstances[].[InstanceId,CurrentState.Name]' --output text | sed 's/^/   /'
    # shellcheck disable=SC2086
    aws ec2 wait instance-terminated --instance-ids $IDS
else
    echo "   none"
fi

echo "== security group"
SG_ID="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$ET_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -n "$SG_ID" ] && [ "$SG_ID" != None ]; then
    # The interfaces of a terminated instance take a moment to let go of it.
    for _ in $(seq 1 12); do
        if aws ec2 delete-security-group --group-id "$SG_ID" 2>/dev/null; then
            echo "   deleted $SG_ID"
            break
        fi
        sleep 5
    done
else
    echo "   none"
fi

rm -f "$STATE"/{easytier_id,easytier_ip,easytier_sg_id,easytier_verify.log}
echo
"$LANE/status.sh"
