
# this ugly hack necessitated by Ubuntu... grrr...
SYSPREFIX=$(shell python3 -c 'import site;print(site.getsitepackages()[0])' | sed -e 's|/[^/]\+/[^/]\+/[^/]\+$$||')
# try to find the architecture-neutral lib dir by looking for one of our expected prereqs... double grrr...
PYLIBDIR=$(shell python3 -c 'import site;import os.path;print([d for d in site.getsitepackages() if os.path.exists(d+"/flask")][0])')

CONFDIR=/home/${DAEMONUSER}/groups/config

ifeq ($(wildcard /etc/httpd/conf.d),/etc/httpd/conf.d)
		HTTPSVC=httpd
else
		HTTPSVC=apache2
endif

HTTPDCONFDIR=/etc/$(HTTPSVC)/conf.d
WSGISOCKETPREFIX=/var/run/$(HTTPSVC)/wsgi
DAEMONUSER=derivagrps

# turn off annoying built-ins
.SUFFIXES:

INSTALL_SCRIPT=./install-script

# make this the default target
install: config config/groups_config.json config
		pip3 install .

testvars:
		@echo DAEMONUSER=$(DAEMONUSER)
		@echo CONFDIR=$(CONFDIR)
		@echo SYSPREFIX=$(SYSPREFIX)
		@echo HTTPDCONFDIR=$(HTTPDCONFDIR)
		@echo WSGISOCKETPREFIX=$(WSGISOCKETPREFIX)
		@echo PYLIBDIR=$(PYLIBDIR)

deploy: install force

redeploy: uninstall deploy

config/wsgi_deriva_groups.conf: config/wsgi_deriva_groups.conf.in force
		./install-script -M sed -R @PYLIBDIR@=$(PYLIBDIR) @WSGISOCKETPREFIX@=$(WSGISOCKETPREFIX) @DAEMONUSER@=$(DAEMONUSER) -o root -g root -m a+r -p -D $< $@

uninstall: force
		-pip3 uninstall -y deriva-groups

force:

