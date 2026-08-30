# Put both packages on PYTHONPATH so `python -m neutrino_hub.cli.<name>` and
# `python -m neutrino_agent.cli` resolve from a checkout. Source this, do not
# execute it:
#
#     source set_env.sh
#
NEUTRINO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export PYTHONPATH="${NEUTRINO_ROOT}/hub:${NEUTRINO_ROOT}/agent${PYTHONPATH:+:${PYTHONPATH}}"
