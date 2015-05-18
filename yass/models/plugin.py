# YASS, Yet Another Subdomainer Software
# Copyright 2015 Francesco Marano (@mrnfrancesco) and individual contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import re
import time
import sys

from pyquery import PyQuery

from helpers import without_duplicates
from models.options import Options


__all__ = ['PluginBase']


class PluginMeta(type):
    """
    Metaclass for all plugins
    """

    def __new__(mcs, name, bases, attrs):
        super_new = super(PluginMeta, mcs).__new__

        # Ensure initialization is only performed for subclasses of Plugin
        # (excluding Plugin class itself).
        parents = [b for b in bases if isinstance(b, PluginMeta)]
        if not parents:
            return super_new(mcs, name, bases, attrs)

        # Create the class.
        module = attrs.pop('__module__')
        new_class = super_new(mcs, name, bases, {'__module__': module})
        attr_meta = attrs.pop('Meta', None)
        if not attr_meta:
            meta = getattr(new_class, 'Meta', None)
        else:
            meta = attr_meta
        base_meta = getattr(new_class, '_meta', None)

        setattr(new_class, '_meta', Options(meta))
        if base_meta and not base_meta.abstract:
            # Non-abstract child classes inherit some attributes from their
            # non-abstract parents.
            for attr in base_meta.__dict__.keys():
                if not hasattr(meta, attr):
                    setattr(new_class._meta, attr, getattr(base_meta, attr))

        # Add all attributes to the class.
        for obj_name, obj in attrs.items():
            setattr(new_class, obj_name, obj)

        return new_class


def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""
    # This requires a bit of explanation: the basic idea is to make a dummy
    # metaclass for one level of class instantiation that replaces itself with
    # the actual metaclass.
    class metaclass(meta):
        def __new__(cls, name, this_bases, d):
            return meta(name, bases, d)

    return type.__new__(metaclass, 'temporary_class', (), {})


class PluginBase(with_metaclass(PluginMeta)):
    """Plugin base class"""

    def __init__(self, domain, *args, **kwargs):
        self.domain = domain
        # set options custom/default value
        self.exclude_subdomains = kwargs.pop('exclude_subdomains', None)
        if kwargs:
            raise AttributeError(
                "Unknown attributes in plugin initialization ({keys})".format(
                    keys=', '.join(kwargs.keys())
                )
            )

    def extract(self, elements):
        """
        Extract data from given HTML elements

        :param elements: HTML elements obtained with PyQuery execution
        :type strings: list[Element]
        :return: extracted data
        :rtype: list[str]
        """
        return [element.text_content() for element in elements]

    def clean(self, urls):
        """
        Clean subdomains URLs from noise

        :param urls: an ensamble of URLs to clean
        :type urls: str [, str [, ...]]
        :return: cleaned subdomains URLs
        :rtype: list[str]
        """
        subdomains = []
        regexp = re.compile(r'(.+://)?(?P<subdomain>(.*){domain})[/\?].*'.format(domain=self.domain))
        for url in urls:
            match = regexp.match(url)
            if match and match.group('subdomain'):
                subdomains.append(match.group('subdomain'))
        return subdomains

    def url(self, exclude_subdomains=None):
        """
        Build the search query URL sring

        :param exclude_subdomains: subdomains to exclude from the search
        :type exclude_subdomains: list[str]
        :param page: results page to ask for
        :type page: int
        :return: URL to use as search query
        :rtype: str
        """
        meta = self._meta

        url = "{url}?{query_param}={include}{domain}".format(
            url=meta.search_url,
            query_param=meta.query_param,
            include=meta.include_param,
            domain=self.domain
        )

        excluded_subdomains = without_duplicates((exclude_subdomains or []) + (self.exclude_subdomains or []))

        if excluded_subdomains:
            url += '+' + '+'.join([
                "{exclude}{subdomain}".format(exclude=meta.exclude_param, subdomain=excluded_domain)
                for excluded_domain in excluded_subdomains
            ])

        return url

    def run(self):
        meta = self._meta
        collected_subdomains = []

        processing_symbols = ['|', '/', '-', '\\']
        index = 0

        while True:
            sys.stdout.write(
                "[{symbol}] Collecting subdomains with {plugin_name} ({requests} request(s) executed)\r".format(
                    symbol=processing_symbols[index % len(processing_symbols)],
                    plugin_name=self.__class__.__name__,
                    requests=index
                )
            )
            sys.stdout.flush()
            index = (index + 1)

            url = self.url(exclude_subdomains=collected_subdomains)

            elements = []
            try:
                pq = PyQuery(url=url)
                elements = pq(meta.subdomains_selector)
            except Exception as e:
                print "[X] Got an unexpected error during connection ({message})\n" \
                      "\t[-] Aborting {plugin_name} execution".format(
                    message=e.message,
                    plugin_name=self.__class__.__name__
                )
                break

            subdomains = self.clean(self.extract(elements))
            if subdomains:
                collected_subdomains = without_duplicates(collected_subdomains + subdomains)
            else:
                print "[{plugin_name}] Collected {collected} subdomains".format(
                    plugin_name=self.__class__.__name__,
                    collected=len(collected_subdomains)
                )
                break

            if self.domain in collected_subdomains:
                collected_subdomains.remove(self.domain)

            time.sleep(meta.request_delay)  # To avoid error 503 (Service Unavailable), or CAPTCHA

        return collected_subdomains