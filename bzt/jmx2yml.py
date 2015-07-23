#! /usr/bin/env python
import logging
import os
import bzt
from bzt.six import etree
import traceback
import yaml
from optparse import OptionParser, BadOptionError, Option
from copy import deepcopy
from collections import namedtuple
# from collections import OrderedDict

KNOWN_TAGS = ["hashTree", "jmeterTestPlan", "TestPlan", "ResultCollector",
              "HTTPSamplerProxy",
              "ThreadGroup",
              "kg.apc.jmeter.timers.VariableThroughputTimer",
              "kg.apc.jmeter.threads.SteppingThreadGroup",
              "DNSCacheManager",
              "HeaderManager",
              "CacheManager",
              "CookieManager",
              "ConfigTestElement",
              "DurationAssertion",
              "ConstantTimer",
              "RegexExtractor",
              "HtmlExtractor",
              "com.atlantbh.jmeter.plugins.jsonutils.jsonpathextractor.JSONPathExtractor",
              "com.atlantbh.jmeter.plugins.jsonutils.jsonpathassertion.JSONPathAssertion",
              "ResponseAssertion",
              "CSVDataSet",
              "GenericController",
              "ResultCollector"]


class Converter(object):
    def __init__(self):
        logging.basicConfig()
        self.log = logging.getLogger(self.__class__.__name__)
        self.log.setLevel('DEBUG')
        self.xml_tree = None
        self.jmx_file = None
        self.global_objects = []
        self.scenario = {"execution": None, "scenarios": None}

    def load_jmx(self, file_path):
        """
        Load jmx file as lxml etree
        :return:
        """
        self.log.debug('Loading jmx file %s', file_path)

        file_path = os.path.abspath(os.path.expanduser(file_path))

        if os.path.exists(file_path):
            try:
                self.tree = etree.fromstring(open(file_path, "rb").read())
                self.jmx_file = file_path
            except BaseException:
                self.log.error("Error while loading jmx file: %s", traceback.format_exc())
        else:
            self.log.error("File %s does not exist", file_path)

    def get_bool_prop(self, element, prop_name):
        """
        Gets bool prop from element
        :param element:
        :param prop_name:
        :return:
        """
        prop_element = element.find(".//boolProp[@name='" + prop_name + "']")
        if prop_element is not None and prop_element.text:
            if prop_element.text.lower() == 'true':
                return True
            elif prop_element.text.lower() == 'false':
                return False
        else:
            self.log.warning("boolProp %s was not found in %s element!", prop_name, element.tag)
            return None

    def get_string_prop(self, element, prop_name, default=None):
        """
        Gets string prop from element
        :param element:
        :param prop_name:
        :return:
        """
        prop_element = element.find(".//stringProp[@name='" + prop_name + "']")
        if prop_element is not None and prop_element.text:
            return prop_element.text
        else:
            return default

    def get_concurrency(self, element):
        """
        concurrency option in tg execution settings
        :return:
        """
        concurrency = self.get_option_string_with_default(element, 'ThreadGroup.num_threads', "concurrency", 1)
        return concurrency

    def get_ramp_up(self, element):
        """
        ramp_up option in tg settings
        :param element:
        :return:
        """
        ramp_up = self.get_option_string_with_default(element, 'ThreadGroup.ramp_time', "ramp-up", 1)
        return ramp_up

    def get_iterations(self, element):
        """
        hold-for option in tg execution settings
        :param element:
        :return:
        """
        controller_element = element.find('.//elementProp')
        iterations = self.get_option_string_with_default(controller_element, 'LoopController.loops', "iterations", 1)
        return iterations

    def get_option_string_with_default(self, element, prop_name, opt_name, default):
        """

        :param element:
        :return: dict
        """
        result = {}
        if element is not None:
            prop_vaulue = self.get_string_prop(element, prop_name)
            if prop_vaulue and int(prop_vaulue) != default:
                result[opt_name] = int(prop_vaulue)
        return result

    def get_request_body(self, http_sampler_element):
        """
        Get body params from sampler
        :param http_sampler_element:
        :return: dict
        """
        # raw_body = http_sampler_element.find(".//boolProp[@name='HTTPSampler.postBodyRaw']")
        raw_body = self.get_bool_prop(http_sampler_element, 'HTTPSampler.postBodyRaw')
        if raw_body:
            http_args_element = http_sampler_element.find(".//elementProp").find(".//collectionProp").find(
                ".//elementProp")
            body = self.get_string_prop(http_args_element,
                                        'Argument.value')  # http_args_element.find(".//stringProp[@name='Argument.value']").text
            if body:
                return {"body": body}
            else:
                return {}
        else:
            body_params = {}
            http_args_collection = http_sampler_element.find(".//elementProp").find(".//collectionProp").findall(
                ".//elementProp")
            for element in http_args_collection:
                body_params[element.get("name")] = self.get_string_prop(element, 'Argument.value')
            if body_params:
                return {"body": body_params}
            else:
                return {}

    def get_headers(self, element):
        """
        Get local request headers
        :return:
        """
        headers = {}
        element_hashtree = element.getnext()
        if element_hashtree is not None and element_hashtree.tag == "hashTree":
            headers_elements = [element for element in element_hashtree.iterchildren() if
                                element.tag == "HeaderManager"]  # element_hashtree.findall(".//HeaderManager")
            for headers_element in headers_elements:
                if headers_element is not None:
                    for header in headers_element.find(".//collectionProp").findall(".//elementProp"):
                        header_name = self.get_string_prop(header, 'Header.name')
                        header_value = self.get_string_prop(header, 'Header.value')
                        if header_name and header_value:
                            headers[header_name] = header_value
        if headers:
            return {"headers": headers}
        else:
            return headers

    def get_store_cache(self, element):
        """
        store-cache option
        :param element:
        :return:
        """
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            cache_managers = [element for element in hashtree.iterchildren() if element.tag == "CacheManager"]
            if cache_managers:
                return {"store-cache": True}
        return {}

    def get_store_cookie(self, element):
        """
        store-cookie option
        :param element:
        :return:
        """
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            cookie_managers = [element for element in hashtree.iterchildren() if element.tag == "CookieManager"]
            if cookie_managers:
                return {"store-cookie": True}
        return {}

    def get_dns_mgr(self, element):
        """
        use-dns-cache-mgr option
        :param element:
        :return:
        """
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            cookie_managers = [element for element in hashtree.iterchildren() if element.tag == "DNSCacheManager"]
            if cookie_managers:
                return {"use-dns-cache-mgr": True}
        return {}

    def get_constant_timer(self, element):
        """
        think-time option
        :param element:
        :return:
        """
        timer = {}
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            timer_element = [element for element in hashtree.iterchildren() if element.tag == "ConstantTimer"]
            if timer_element:
                timer_delay = self.get_string_prop(timer_element[0], 'ConstantTimer.delay')
                if timer_delay:
                    timer = {"think-time": timer_delay + "ms"}
        return timer

    def get_http_request_defaults(self, element):
        """
        timeout
        default-address
        keepalive
        retrieve-resources
        concurrent-pool-size
        :param element:
        :return:
        """
        request_defaults = {}
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            http_defaults = [element for element in hashtree.iterchildren() if element.tag == "ConfigTestElement"]
            if http_defaults:
                http_defaults = http_defaults[0]
                url_info = self.extract_url_info(http_defaults)
                if url_info:
                    default_address = self.make_url(url_info)
                    if default_address:
                        request_defaults["default-address"] = default_address
                if url_info.timeout: request_defaults["timeout"] = url_info.timeout + "ms"
                if url_info.retrieve_resources is not None: request_defaults[
                    "retrieve-resources"] = url_info.retrieve_resources
                # TODO: Chick if retrieve_resources enabled then set concurrency
                if url_info.retrieve_concurrency: request_defaults["concurrent-pool-size"] = int(
                    url_info.retrieve_concurrency)
        return request_defaults

    def make_url(self, url_info):
        """

        :return: string
        """
        path = "/" if not url_info.path else url_info.path
        port = "" if not url_info.port or url_info.port == "80" else ":" + url_info.port
        protocol = "http" if not url_info.protocol else url_info.protocol
        if url_info.domain:
            return protocol + "://" + url_info.domain + port + path
        return ""

    def extract_url_info(self, element):
        """
        extracts domain, port, etc from element
        :return:
        """
        http_sampler_info = namedtuple("http_sampler_info",
                                       ["domain", "port", "timeout", "protocol", "path", "method", "retrieve_resources",
                                        "retrieve_concurrency"])
        if element is not None:
            domain = self.get_string_prop(element, 'HTTPSampler.domain')
            port = self.get_string_prop(element, 'HTTPSampler.port')
            timeout = self.get_string_prop(element, 'HTTPSampler.connect_timeout')
            protocol = self.get_string_prop(element, 'HTTPSampler.protocol')
            path = self.get_string_prop(element, 'HTTPSampler.path')
            retrieve_resources = self.get_bool_prop(element, 'HTTPSampler.image_parser')
            retrieve_concurrency = self.get_string_prop(element, 'HTTPSampler.concurrentPool')
            method = self.get_string_prop(element, 'HTTPSampler.method')
            url_info = http_sampler_info(domain, port, timeout, protocol, path, method, retrieve_resources,
                                         retrieve_concurrency)
            return url_info
        self.log.warning("Url info failed, element is None.")
        return None

    def get_request_base(self, element):
        """
        Converts to dict
        :return:
        """
        base_settings = {}
        url_info = self.extract_url_info(element)
        if url_info is not None:
            full_url = self.make_url(url_info)
            if full_url:
                base_settings["url"] = full_url
            if url_info.method:
                base_settings["method"] = url_info.method
        if element.get("testname"):
            base_settings["label"] = element.get("testname")

        return base_settings

    def get_data_sources(self, element):
        """
        data-sources option
        :param element:
        :return: list of dicts
        """
        data_sources = []
        hashtree = element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            data_sources_elements = [element for element in hashtree.iterchildren() if
                                     element.tag == "CSVDataSet"]  # hashtree.findall(".//CSVDataSet")
            # data_sources_elements = [element for element in hashtree.findall(".//CSVDataSet") if self.get_depth(element) == depth]
            # data_sources_elements = hashtree.findall(".//CSVDataSet")
            for data_source in data_sources_elements:
                # self.log.debug(self.get_depth(data_source))
                self.log.debug("datasource file: %s", data_source.get("testname"))
                # if self.get_depth(data_source) != depth:
                #     continue
                if data_source is not None:
                    data_source_dict = {}

                    f_name_prop = self.get_string_prop(data_source, 'filename')

                    if f_name_prop:
                        data_source_dict["path"] = f_name_prop
                    else:
                        self.log.warning("File name was not set in %s, skipping", data_source.tag)
                        continue

                    delimiter_prop = self.get_string_prop(data_source, 'delimiter')
                    if delimiter_prop:
                        data_source_dict["delimiter"] = delimiter_prop
                    else:
                        self.log.warning("Delimiter was not set in %s, using default - ','", data_source.tag)
                        data_source_dict["delimiter"] = ","

                    quoted_prop = self.get_bool_prop(data_source, 'quotedData')
                    if quoted_prop is not None:
                        data_source_dict["quoted"] = quoted_prop
                    else:
                        self.log.warning("Quoted property was not set in %s, using default False", data_source.tag)
                        data_source_dict["quoted"] = False

                    loop_prop = self.get_bool_prop(data_source, 'recycle')
                    if loop_prop is not None:
                        data_source_dict["recycle"] = loop_prop
                    else:
                        self.log.warning("Loop property was not set in %s, using default False", data_source.tag)
                        data_source_dict["recycle"] = False

                    data_sources.append(data_source_dict)
        if data_sources:
            return {"data-sources": data_sources}
        else:
            return {}

    def get_request_timeout(self, element):
        timeout = {}
        timeout_prop = self.get_string_prop(element, 'HTTPSampler.connect_timeout')
        if timeout_prop:
            timeout = {"timeout": timeout_prop + "ms"}
        return timeout

    def get_extractors(self, http_request_element):
        """
        Gets
        :param http_request_element:
        :return:
        """
        extractors = {}
        regexp_extractors = self.get_regexp_extractor(http_request_element)
        if regexp_extractors: extractors.update({"extract-regexp": regexp_extractors})
        jsonpath_extractors = self.get_json_path_extractors(http_request_element)
        if jsonpath_extractors: extractors.update({"extract-jsonpath": jsonpath_extractors})
        return extractors

    def get_regexp_extractor(self, http_request_element):
        """
        extract-regexp option
        :param http_request_element:
        :return:
        """
        regexp_extractors = {}
        request_hashtree = http_request_element.getnext()
        if request_hashtree is not None and request_hashtree.tag == "hashTree":
            extractor_elements = request_hashtree.findall(".//RegexExtractor")

            for extractor_element in extractor_elements:
                regexp_extractor = {}

                if extractor_element is not None:
                    refname_prop = self.get_string_prop(extractor_element, 'RegexExtractor.refname')

                    if refname_prop is not None:
                        extractor_props = {}

                        regexp_prop = self.get_string_prop(extractor_element, 'RegexExtractor.regex')

                        if regexp_prop:
                            extractor_props["regexp"] = regexp_prop
                        else:
                            self.log.warning("No regexp expression found in %s, skipping", extractor_element.tag)
                            continue

                        default_prop = self.get_string_prop(extractor_element, 'RegexExtractor.default')

                        if default_prop:
                            extractor_props["default"] = default_prop
                        else:
                            self.log.warning("No default value found in %s", extractor_element.tag)
                            extractor_props["default"] = ""

                        match_no_prop = self.get_string_prop(extractor_element,
                                                             'RegexExtractor.RegexExtractor.match_number')

                        if match_no_prop:
                            extractor_props["match-no"] = int(match_no_prop)
                        else:
                            self.log.warning("No match number found in %s", extractor_element.tag)
                            extractor_props["match-no"] = 0

                        template_prop = self.get_string_prop(extractor_element, 'RegexExtractor.template')

                        if template_prop:
                            extractor_props["template"] = int(template_prop)
                        else:
                            self.log.warning("No template property found in %s", extractor_element.tag)
                            extractor_props["template"] = 1

                        if refname_prop:
                            refname = refname_prop
                        else:
                            self.log.warning("No refname property found in %s, generating", extractor_element.tag)
                            refname = str(refname_prop.__hash__())

                        regexp_extractor.update({refname: extractor_props})

                    else:
                        self.log.warning("refname property element not found in %s skipping", extractor_element.tag)
                        continue

                regexp_extractors.update(regexp_extractor)

        return regexp_extractors

    def get_json_path_extractors(self, http_request_element):
        """
        extract-jsonpath option
        :param http_request_element:
        :return:
        """

        json_path_extractors = {}

        hashtree = http_request_element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            property_pattern = ".//com.atlantbh.jmeter.plugins.jsonutils.jsonpathextractor.JSONPathExtractor"
            extractor_elements = [element for element in hashtree.iterchildren() if element.tag == property_pattern]
            for extractor_element in extractor_elements:
                json_path_extractor = {}

                if extractor_element is not None:
                    varname_prop = self.get_string_prop(extractor_element, 'VAR')

                    if varname_prop is not None:
                        extractor_props = {}

                        jsonpath_prop = self.get_string_prop(extractor_element, 'JSONPATH')

                        if jsonpath_prop:
                            extractor_props["jsonpath"] = jsonpath_prop
                        else:
                            self.log.warning("No json expression found in %s, skipping element", extractor_element.tag)
                            continue

                        default_prop = self.get_string_prop(extractor_element, 'DEFAULT')

                        if default_prop:
                            extractor_props["default"] = default_prop
                        else:
                            self.log.warning("No default value found in %s", extractor_element.tag)
                            extractor_props["default"] = ""

                        if varname_prop:
                            varname = varname_prop
                        else:
                            self.log.warning("Not found varname in %s, generating", extractor_element.tag)
                            varname = str(varname_prop.__hash__())

                        json_path_extractor.update({varname: extractor_props})
                json_path_extractors.update(json_path_extractor)

        return json_path_extractors

    def get_assertions(self, http_request_element):
        """
        assertions:
        assert, assert-jsonpath
        :param http_request_element:
        :return:
        """
        assertions = {}
        simple_assertions = self.get_response_assertions(http_request_element)
        if simple_assertions: assertions.update({"assert": simple_assertions})
        jsonpath_assertions = self.get_jsonpath_assertions(http_request_element)
        if jsonpath_assertions: assertions.update({"assert-jsonpath": jsonpath_assertions})
        return assertions

    def get_response_assertions(self, http_request_element):
        """
        list of dicts
        :param http_request_element:
        :return: dict
        """
        response_assertions = []
        subjects = {"Assertion.response_data": "body", "Assertion.response_headers": "headers",
                    "Assertion.response_code": "http-code"}
        test_types = {'6': (True, True), '2': (True, False), '20': (False, True),
                      '16': (False, False)}  # (is_regexp, is_inverted)
        hashtree = http_request_element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            response_assertion_elements = [element for element in hashtree.iterchildren() if
                                     element.tag == "ResponseAssertion"]

            for response_assertion_element in response_assertion_elements:
                response_assertion = {}
                assertion_collection = response_assertion_element.find(
                    ".//collectionProp[@name='Asserion.test_strings']")

                if assertion_collection is None:
                    self.log.warning("Collection not found in %s, skipping", response_assertion_element.tag)
                    continue

                test_string_props = assertion_collection.findall(".//stringProp")
                test_strings = []
                for string_prop in test_string_props:
                    if string_prop is not None and string_prop.text:
                        test_strings.append(string_prop.text)
                if not test_strings:
                    self.log.warning("No test strings in %s, skipping", response_assertion_element.tag)
                    continue

                response_assertion["contains"] = test_strings

                test_field_prop = self.get_string_prop(response_assertion_element, 'Assertion.test_field')

                if test_field_prop:
                    test_subject = subjects.get(test_field_prop, "body")
                else:
                    self.log.warning("No test subject provided in %s, skipping", response_assertion_element.tag)
                    continue

                response_assertion["subject"] = test_subject

                test_type_element = response_assertion_element.find(".//*[@name='Assertion.test_type']")

                if test_type_element is not None and test_type_element.text:
                    test_type = test_types.get(test_type_element.text)

                    if test_type:
                        is_regexp, is_inverted = test_type
                        response_assertion["regexp"] = is_regexp
                        response_assertion["not"] = is_inverted
                    else:
                        self.log.warning("Unknown test type in %s, skipping", response_assertion_element.tag)
                        continue
                else:
                    self.log.warning("No test subject provided in %s, skipping", response_assertion_element.tag)
                    continue

                response_assertions.append(response_assertion)
        return response_assertions

    def get_jsonpath_assertions(self, http_request_element):
        """
        assert-jsonpath option
        :param http_request_element:
        :return: list of dicts
        """
        json_path_assertions = []

        hashtree = http_request_element.getnext()
        if hashtree is not None and hashtree.tag == "hashTree":
            pattern = "com.atlantbh.jmeter.plugins.jsonutils.jsonpathassertion.JSONPathAssertion"
            json_path_assertion_elements = [element for element in hashtree.iterchildren() if element.tag == pattern]

            for json_path_assertion_element in json_path_assertion_elements:
                json_path_assertion = {}

                json_path_element = self.get_string_prop(json_path_assertion_element, 'JSON_PATH')

                if json_path_element:
                    json_path_assertion["jsonpath"] = json_path_element
                else:
                    self.log.warning("No json path in %s, skipping", json_path_assertion_element.tag)
                    continue

                expected_vaule_element = self.get_string_prop(json_path_assertion_element, 'EXPECTED_VALUE')

                if expected_vaule_element is not None and expected_vaule_element:
                    json_path_assertion["expected-value"] = expected_vaule_element
                else:
                    json_path_assertion["expected-value"] = None

                # TODO: expand, use default values
                json_path_assertion["validate"] = False
                json_path_assertion["expect-null"] = False
                json_path_assertion["invert"] = False

                json_path_assertions.append(json_path_assertion)

        return json_path_assertions

    def convert_etree_to_dict(self, etree_element, params):
        result_dict = {}
        for param, value in params.items():
            val = etree_element.find("*[@name=" + "'" + value + "'" + "]").text
            if val:
                result_dict[param] = val
                # else:
                #     result_dict[param] = ""
        return result_dict

    def get_thread_groups(self):
        """
        Get all thread groups from jmx, convert to dict.
        :return: dict
        """
        # testplan_dict = {"scenarios": {}, "execution": {"scenario": []}}
        testplan_dict = {"scenarios": {}, "execution": []}

        self.log.debug("Processing thread groups...")
        tg_etree_elements = self.tree.findall(".//ThreadGroup")
        self.get_global_objects()

        if tg_etree_elements:
            self.log.debug("Total thread groups: %d", len(tg_etree_elements))

            for tg_etree_element in tg_etree_elements:

                tg_scenario_settings = self.get_tg_scenario_settings(tg_etree_element)

                tg_name = tg_etree_element.get("testname")
                if not tg_name: tg_name = str(tg_etree_element.__hash__())
                tg_execution_settings = {"scenario": tg_name}
                ht_element = tg_etree_element.getnext()
                if ht_element.tag == "hashTree":
                    request_elements = ht_element.findall(".//HTTPSamplerProxy")
                    self.log.debug("Total http samplers in tg groups: %d", len(request_elements))

                    for request_element in request_elements:
                        request_config = self.get_request_settings(request_element)
                        tg_scenario_settings["requests"].append(request_config)

                tg_scenario_dict = {tg_name: tg_scenario_settings}
                td_executions_dict = {"scenario": tg_name}
                td_executions_dict.update(self.get_tg_execution_settings(tg_etree_element))
                testplan_dict["scenarios"].update(tg_scenario_dict)
                testplan_dict["execution"].append(td_executions_dict)
                # testplan_dict["execution"]["scenario"].append(tg_element.get("testname"))
            # testplan_dict["execution"]["concurency"] = summ_concurrency
            self.scenario = testplan_dict
        else:
            self.log.warning("No thread groups was found!")

    def get_request_settings(self, request_element):
        """
        Gets all possible request settings
        :param request_element:
        :return: dict
        """
        request_config = {}
        request_config.update(self.get_request_base(request_element))
        request_config.update(self.get_request_body(request_element))
        request_config.update(self.get_headers(request_element))
        request_config.update(self.get_constant_timer(request_element))
        request_config.update(self.get_request_timeout(request_element))
        request_config.update(self.get_extractors(request_element))
        request_config.update(self.get_assertions(request_element))
        return request_config

    def get_tg_scenario_settings(self, tg_etree_element):
        """
        Gets all possible tg settings and applies global overrides
        :param tg_etree_element:
        :return:
        """
        default_tg_settings = {"store-cookie": False, "store-cache": False, "use-dns-cache-mgr": False}
        global_tg_settings = self.get_global_tg_settings()
        tg_settings = {"requests": []}
        tg_settings.update(default_tg_settings)
        tg_settings.update(self.get_data_sources(tg_etree_element))
        tg_settings.update(self.get_headers(tg_etree_element))
        tg_settings.update(self.get_store_cache(tg_etree_element))
        tg_settings.update(self.get_store_cookie(tg_etree_element))
        tg_settings.update(self.get_dns_mgr(tg_etree_element))
        tg_settings.update(self.get_assertions(tg_etree_element))
        # apply global test plan settings:
        self.apply_global_tg_settings(global_tg_settings, tg_settings)
        # those settings override global:

        tg_settings.update(self.get_constant_timer(tg_etree_element))
        tg_settings.update(self.get_http_request_defaults(tg_etree_element))
        return tg_settings

    def get_tg_execution_settings(self, tg_etree_element):
        """
        Gets execution settings
        :param tg_etree_element:
        :return: dict
        """
        execution_settings = {}
        execution_settings.update(self.get_concurrency(tg_etree_element))
        execution_settings.update(self.get_ramp_up(tg_etree_element))
        execution_settings.update(self.get_iterations(tg_etree_element))
        return execution_settings

    def get_global_objects(self):
        """
        list of global objects in test plan
        :return:
        """

        self.global_objects = []
        ht_object = self.tree.find(".//hashTree").find(".//TestPlan").getnext()
        for obj in ht_object.iterchildren():
            if obj.tag != 'hashTree' and obj.tag != 'ThreadGroup':
                self.global_objects.append(obj)

    def get_global_tg_settings(self):
        """
        :return: dict
        """
        default_tg_settings = {}
        testplan_element = self.tree.find(".//TestPlan")
        glob_headers = self.get_headers(testplan_element)
        glob_data_sources = self.get_data_sources(testplan_element)
        glob_store_cache = self.get_store_cache(testplan_element)
        glob_store_cookie = self.get_store_cookie(testplan_element)
        glob_dns_mgr = self.get_dns_mgr(testplan_element)
        glob_c_timer = self.get_constant_timer(testplan_element)
        glob_request_defaults = self.get_http_request_defaults(testplan_element)
        glob_assertions = self.get_assertions(testplan_element)
        default_tg_settings.update(glob_headers)
        default_tg_settings.update(glob_data_sources)
        default_tg_settings.update(glob_store_cache)
        default_tg_settings.update(glob_store_cookie)
        default_tg_settings.update(glob_dns_mgr)
        default_tg_settings.update(glob_c_timer)
        default_tg_settings.update(glob_request_defaults)
        default_tg_settings.update(glob_assertions)

        return default_tg_settings

    def apply_global_tg_settings(self, defaults, tg_dict, override=True):
        for default_key, default_value in defaults.items():
            if isinstance(default_value, list):
                # tmp = defaults[default].copy()
                if default_key in tg_dict.keys():
                    tg_dict[default_key].extend(deepcopy(default_value))
                else:
                    tg_dict[default_key] = deepcopy(default_value)
            elif isinstance(default_value, dict):
                if default_key in tg_dict.keys():
                    tg_dict[default_key].update(default_value)
                else:
                    tg_dict[default_key] = defaults[default_key]
            else:
                if default_key not in tg_dict.keys():
                    tg_dict[default_key] = defaults[default_key]
                else:
                    if override:
                        tg_dict[default_key] = defaults[default_key]

    def convert(self, file_path):
        """
        Converts all
        :return:
        """
        self.load_jmx(file_path)
        if self.jmx_file:
            self.clean_disabled_elements(self.tree)
            self.clean_jmx_tree(self.tree)
            self.get_thread_groups()
            self.dump_yaml(file_path + ".yml")

    def check_if_disabled(self, element):
        """
        Returns True if any parent element is disabled
        :return:
        """
        parent_disabled = False
        parent = element.getparent()

        while parent is not None:
            if parent.get('enabled') == 'false':
                parent_disabled = True
                break
            parent = parent.getparent()

        return parent_disabled

    def get_depth(self, element):
        return len([ancestor for ancestor in element.iterancestors()])

    def remove_element(self, element):
        sibling = element.getnext()
        if sibling is not None and sibling.tag == "hashTree":
            # self.log.debug("Removing hashtree %s, %s", sibling.tag, sibling.get("name"))
            sibling.getparent().remove(sibling)

        element.getparent().remove(element)

    def clean_disabled_elements(self, element):

        for subelement in element.iter():
            # self.log.debug("subelement %s %s %s %d %s", subelement.tag, subelement.get("name", ""),
            #                subelement.get("testclass", ""), self.get_depth(subelement), subelement.text)
            if subelement.tag.endswith("prop"):
                continue
            if subelement.get("enabled") == 'false':
                self.log.debug("Removing disabled element %s, %s", element.tag, element.get("name"))
                self.remove_element(subelement)
                self.clean_disabled_elements(element)
                return

    def clean_jmx_tree(self, element):
        """
        Purge disabled and unknown elements from etree
        :return:
        """
        for subelement in element.iter():
            # self.log.debug("subelement %s %s %s %d %s", subelement.tag, subelement.get("name", ""),
            #                    subelement.get("testclass", ""), self.get_depth(subelement), subelement.text)
            if subelement.tag.lower().endswith("prop"):
                continue

            if subelement.tag not in KNOWN_TAGS:
                self.log.debug("Removing unknown element: %s", subelement.tag)
                self.remove_element(subelement)
                self.clean_jmx_tree(element)
                return

    def dump_yaml(self, file_path):
        with open(file_path, "wt") as fds:
            yaml.dump(self.scenario, fds, default_flow_style=False, explicit_start=True)


def main():
    usage = "Usage: jmx2yml [input jmx file]"
    parser = OptionParser(usage=usage, prog="jmx2yml")
    parser.add_option('-v', '--verbose', help="Prints all logging messages to console")
    parsed_options, args = parser.parse_args()
    converter = Converter()
    converter.convert(args[0])


if __name__ == "__main__":
    main()
