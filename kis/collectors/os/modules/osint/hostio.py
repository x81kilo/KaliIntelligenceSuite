# -*- coding: utf-8 -*-
"""
run tool kismanage on each identified in-scope second-level domain to identify relationships to other second-level
domains via host.io. depending on the number of domains in the current workspace, it might be desired to limit the
number of OS commands by using the optional argument --filter
"""

__author__ = "Lukas Reiter"
__license__ = "GPL v3.0"
__copyright__ = """Copyright 2018 Lukas Reiter

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
__version__ = 0.1

import logging
from database.model import Source
from database.model import Command
from collectors.os.core import PopenCommand
from collectors.core import JsonUtils
from collectors.os.modules.osint.core import BaseKisImportDomain
from collectors.os.modules.core import DomainCollector
from collectors.apis.hostio import HostIo
from view.core import ReportItem
from sqlalchemy.orm.session import Session


logger = logging.getLogger('hostio')


class CollectorClass(BaseKisImportDomain, DomainCollector):
    """This class implements a collector module that is automatically incorporated into the application."""

    def __init__(self, **kwargs):
        super().__init__(priority=127,
                         timeout=0,
                         argument_name="--hostio",
                         source=HostIo.SOURCE_NAME,
                         delay_min=1,
                         **kwargs)
        self._json_utils = JsonUtils()

    @staticmethod
    def get_argparse_arguments():
        return {"help": __doc__, "action": "store_true"}

    def api_credentials_available(self) -> bool:
        """
        This method shall be implemented by sub classes. They should verify whether their API keys are set in the
        configuration file
        :return: Return true if API credentials are set, else false
        """
        return self._api_config.config.get("host.io", "api_url") and \
               self._api_config.config.get("host.io", "api_key") and \
               self._api_config.config.get("host.io", "api_limit")

    def verify_results(self, session: Session,
                       command: Command,
                       source: Source,
                       report_item: ReportItem,
                       process: PopenCommand = None, **kwargs) -> None:
        """This method analyses the results of the command execution.

        After the execution, this method checks the OS command's results to determine the command's execution status as
        well as existing vulnerabilities (e.g. weak login credentials, NULL sessions, hidden Web folders). The
        stores the output in table command. In addition, the collector might add derived information to other tables as
        well.

        :param session: Sqlalchemy session that manages persistence operations for ORM-mapped objects
        :param command: The command instance that contains the results of the command execution
        :param source: The source object of the current collector
        :param report_item: Item that can be used for reporting potential findings in the UI
        :param process: The PopenCommand object that executed the given result. This object holds stderr, stdout, return
        code etc.
        """
        if command.return_code and command.return_code > 0:
            self._set_execution_failed(session=session, command=command)
            return
        for json_object in command.json_output:
            section = "domain"
            if section in json_object:
                item = json_object[section]
                self.add_host_name(session=session,
                                   command=command,
                                   host_name=item,
                                   source=source,
                                   report_item=report_item)
            if "web" in json_object:
                item = json_object["web"]
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="domain",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="redirect",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="links",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_url_from_json(session=session,
                                       json_object=item,
                                       path="url",
                                       command=command,
                                       source=source,
                                       report_item=report_item)
                self.add_host_from_json(session=session,
                                        json_object=item,
                                        path="ip",
                                        command=command,
                                        source=source,
                                        report_item=report_item)
                if "email" in item:
                    for email_str in item["email"].split(","):
                        email_str = email_str.strip()
                        email = self.add_email(session=session,
                                               command=command,
                                               email=email_str,
                                               source=source,
                                               report_item=report_item,
                                               verify=True)
                        if not email:
                            logger.warning("could not add email '{}' to database due to invalid format".format(email_str))
            if "dns" in json_object:
                item = json_object["dns"]
                # add A records
                self.add_host_from_json(session=session,
                                        json_object=item,
                                        path="a",
                                        command=command,
                                        source=source,
                                        report_item=report_item)
                # add MX records
                if "mx" in item:
                    for mx in item["mx"]:
                        mx = mx.split()[-1]
                        self.add_host_name(session=session,
                                           command=command,
                                           host_name=mx,
                                           source=source,
                                           verify=True,
                                           report_item=report_item)
                # add NS records
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="ns",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
            if "ipinfo" in json_object:
                for ip_address, content in json_object["ipinfo"].items():
                    host = self.add_host(session=session,
                                         command=command,
                                         address=ip_address,
                                         source=source,
                                         report_item=report_item)
                    if not host:
                        logger.warning("could not add host '{}' to database due to invalid format".format(ip_address))
                    self.add_network_from_json(session=session,
                                               json_object=content,
                                               path="asn/route",
                                               command=command,
                                               source=source,
                                               report_item=report_item)
                    self.add_host_name_from_json(session=session,
                                                 json_object=content,
                                                 path="asn/domain",
                                                 command=command,
                                                 source=source,
                                                 report_item=report_item)
            if "domains" in json_object:
                item = json_object["domains"]
                # add A records
                self.add_host_from_json(session=session,
                                        json_object=item,
                                        path="ip",
                                        command=command,
                                        source=source,
                                        report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="domains",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
            if "related" in json_object:
                item = json_object["related"]
                self.add_host_from_json(session=session,
                                        json_object=item,
                                        path="ip/*/value",
                                        command=command,
                                        source=source,
                                        report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="ns/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="mx/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="backlinks/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="redirects/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="adsense/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_host_name_from_json(session=session,
                                             json_object=item,
                                             path="googleanalytics/*/value",
                                             command=command,
                                             source=source,
                                             report_item=report_item)
                self.add_email_from_json(session=session,
                                         json_object=item,
                                         path="email/*/value",
                                         command=command,
                                         source=source,
                                         report_item=report_item)
