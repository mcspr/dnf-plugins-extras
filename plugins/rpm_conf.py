# handling packages via 'rpmconf'.
#
# Copyright (C) 2015 Igor Gnatenko
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details. You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA. Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#

import sys
import errno
from dnfpluginsextras import _, logger

import dnf
import filecmp
from rpmconf import rpmconf


class UnattendedRpmConf(rpmconf.RpmConf):

    def __init__(self, *args, **kwargs):
        self.unattended = kwargs.pop('unattended', None)
        super().__init__(*args, **kwargs)

    def _test_duplicate(self, conf_file, other_file):
        if not (self.is_broken_symlink(conf_file) or self.is_broken_symlink(other_file)) \
           and filecmp.cmp(conf_file, other_file):
            return True

        return False

    def _handle_rpmnew(self, conf_file, other_file):
        """Depends on instance attribute `unattended`:

        * `diff` display diff for conf_file and other_file
        * `maintainer` install the package maintainer's version
        * `user` keep currently-installed version

        If attribute is not set, reverts to the original method
        """

        if self._test_duplicate(conf_file, other_file):
            self._remove(other_file)
            return

        if not self.unattended:
            super()._handle_rpmnew(conf_file, other_file)
        elif self.unattended == 'diff':
            self.show_diff(conf_file, other_file)
        elif self.unattended == 'maintainer':
            self._overwrite(other_file, conf_file)
        elif self.unattended == 'user':
            self._remove(other_file)

    def _handle_rpmsave(self, conf_file, other_file):
        """
        Depends on instance attribute `unattended`:

        * `diff` just display diff for conf_file and other_file
        * `maintainer` install (keep) the package maintainer's version
        * `user` return back to the original / saved file

        If attribute is not set, reverts to the original method
        """

        if self._test_duplicate(conf_file, other_file):
            self._remove(other_file)
            return

        if not self.unattended:
            super()._handle_rpmsave(conf_file, other_file)
        elif self.unattended == 'diff':
            self.show_diff(other_file, conf_file)
        elif self.unattended == 'maintainer':
            self._remove(other_file)
        elif self.unattended == 'user':
            self._overwrite(other_file, conf_file)


class Rpmconf(dnf.Plugin):
    name = 'rpmconf'

    def __init__(self, base, cli):
        super().__init__(base, cli)
        self.base = base
        self.packages = []
        self.frontend = None
        self.unattended = None

    def config(self):
        self._interactive = True
        if (not sys.stdin or not sys.stdin.isatty()) \
                or self.base.conf.assumeyes \
                or self.base.conf.assumeno:
            self._interactive = False

        conf = self.read_config(self.base.conf)

        if conf.has_option('main', 'frontend'):
            self.frontend = conf.get('main', 'frontend')
        else:
            self.frontend = None

        if conf.has_option('main', 'unattended'):
            self.unattended = conf.get('main', 'unattended')
            if self.unattended not in ('diff', 'maintainer', 'user'):
                self.unattended = None
        else:
            self.unattended = None

    def resolved(self):
        if not self._interactive:
            return

        tmp = []
        for trans_item in self.base.transaction:
            tmp.append(trans_item.installs())
        for packages in tmp:
            for pkg in packages:
                logger.debug(
                    _("Adding '{}' to list of handling "
                      "packages for rpmconf").format(pkg.name))
                self.packages.append(pkg.name)

    def transaction(self):
        if all((not self.unattended,
                not self._interactive)):
            logger.debug(_("rpmconf plugin will not run in "
                           "non-interactive mode without "
                           "`unattended` turned on"))
            return

        rconf = UnattendedRpmConf(
            packages=self.packages,
            frontend=self.frontend,
            unattended=self.unattended)
        try:
            rconf.run()
        except SystemExit as e:
            if e.code == errno.ENOENT:
                logger.debug(
                    _("ignoring sys.exit from rpmconf "
                      "due to missing MERGE variable"))
            elif e.code == errno.EINTR:
                logger.debug(
                    _("ignoring sys.exit from rpmconf "
                      "due to missing file"))
