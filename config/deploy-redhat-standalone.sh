#!/bin/bash

# Deploy deriva-groups in a simple standalone fashion useful
# on Red Hat flavored systems, e.g. Rocky, Fedora, RHEL.
#
# 1. Deploy via distro's httpd + mod_wsgi
# 2. Provision derivagrps daemon account
# 3. Adjust SE-Linux policy for mod_wsgi sandbox
# 4. Setup default configuration files for deriva-groups
#
# Use idempotent, non-clobbering methods so that a clean
# install leads to a (nearly) usable state, but any local
# customization is preserved.
#
# Default config: (may change)
#
# - syslog logging
# - sqlite backend
#

########
# some helper funcs

TMP_ENV=$(mktemp /tmp/deriva_groups.env.XXXXXX)
TMP_JSON=$(mktemp /tmp/groups_config.json.XXXXX)

cleanup()
{
    rm -f "${TMP_ENV}" "${TMP_JSON}"
}

trap cleanup 0

error()
{
    echo "$@" >&2
    exit 1
}

idempotent_semanage_add()
{
    # args: "type" "filepattern"
    semanage fcontext --add --type "$1" "$2" \
        || semanage fcontext --modify --type "$1" "$2" \
        || error Failed to install SE-Linux context "$1" for "$2"
}
########

# sanity check runtime requirements
[[ $(id -u) -eq 0 ]] || error This script must run as root

[[ -r /etc/redhat-release ]] || error Failed to find /etc/redhat-release

# whitelist systems we think ought to work with this script
case "$(cat /etc/redhat-release)" in
    Rocky\ Linux\ release\ 8*)
        :
        ;;
    Fedora\ release\ 4*)
        :
        ;;
    *)
        error Failed to detect a tested Red Hat OS variant
        ;;
esac

curl -s "https://$(hostname)/" > /dev/null \
    || error Failed to validate connectivity to "https://$(hostname)/"

[[ -f /etc/httpd/conf.d/wsgi.conf ]] \
    || error Failed to detect /etc/httpd/conf.d/wsgi.conf prerequisite

pip3 show deriva-groups >/dev/null \
     || error Failed to detect required deriva-groups package with pip3

# TODO: change if we can use installed data resources instead of source tree
[[ -f pyproject.toml ]] \
    && grep -q 'name = "deriva-groups"' pyproject.toml \
        || error The current working dir must contain the deriva-groups source tree

# idempotently provision the daemon account and homedir
id derivagrps \
    || useradd -m -g apache -r derivagrps \
    || error Failed to create derivagrps daemon account

[[ -d /home/derivagrps ]] \
    || error Failed to detect derivagrps daemon home directory

mkdir -p /home/derivagrps/config \
    && chown root:apache /home/derivagrps/config \
    && chmod u=rwx,g=rx,o= /home/derivagrps/config \
	|| error Failed to provision /home/derivagrps/config sub-dir

mkdir -p /home/derivagrps/secrets \
    && chown root:apache /home/derivagrps/secrets \
    && chmod u=rxw,g=rx,o= /home/derivagrps/secrets \
	|| error Failed to provision /home/derivagrps/secrets sub-dir

mkdir -p /home/derivagrps/state \
    && chown derivagrps:apache /home/derivagrps/state \
    && chmod u=rxw,g=rwx,o= /home/derivagrps/state \
	|| error Failed to provision /home/derivagrps/state sub-dir


# idempotently deploy default configs
[[ -f /etc/httpd/conf.d/wsgi_deriva_groups.conf ]] \
    || install -o root -m u=rw,og=r config/wsgi_deriva_groups.conf /etc/httpd/conf.d/ \
    || error Failed to deploy wsgi_deriva_groups.conf

# TODO: change 
cat > "${TMP_ENV}" <<EOF
DERIVA_GROUPS_APP_BASE_URL="https://$(hostname)/deriva/apps/groups"
DERIVA_GROUPS_CORS_ORIGINS="https://$(hostname)"
DERIVA_GROUPS_AUTH_BASE_URL="https://$(hostname)/authn"
DERIVA_GROUPS_AUDIT_USE_SYSLOG=true
DERIVA_GROUPS_ENABLE_LEGACY_AUTH_API=true
DERIVA_GROUPS_AUTH_ALLOW_BYPASS_CERT_VERIFY=false
DERIVA_GROUPS_STORAGE_BACKEND=sqlite
DERIVA_GROUPS_STORAGE_BACKEND_URL=/home/derivagrps/state/deriva-groups-sqlite.db
EOF
[[ $? = 0 ]] || error Failed to create ${TMP_ENV}

[[ -f /home/derivagrps/config/deriva_groups.env ]] \
    || install -o root -g apache -m u=rw,og=r -T "${TMP_ENV}" /home/derivagrps/config/deriva_groups.env \
    || error Failed to deploy /home/derivagrps/config/deriva_groups.env

# TODO: consider optional config params?
cat > "${TMP_JSON}" <<EOF
{}
EOF

[[ -f /home/derivagrps/config/groups_config.json ]] \
    || install -o root -g apache -m u=rw,og=r -T "${TMP_JSON}" /home/derivagrps/config/groups_config.json \
    || error Failed to deploy /home/derivagrps/config/groups_config.json

# set minimal permissions for SE-Linux sandboxed WSGI daemon
idempotent_semanage_add \
    httpd_sys_content_t \
    '/home/derivagrps/config/.*'

idempotent_semanage_add \
    httpd_sys_content_t \
    '/home/derivagrps/secrets/.*'

idempotent_semanage_add \
    httpd_sys_rw_content_t \
    '/home/derivagrps/state(/.*)?'

restorecon -rv /home/derivagrps/

