import base64
import hashlib
import json
import os.path
import re
import sys
import webbrowser
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

import requests
import yaml

from buildtest.defaults import BUILD_REPORT, console
from buildtest.utils.file import is_file, resolve_path
from buildtest.utils.tools import deep_get


def cdash_cmd(args, default_configuration=None, open_browser=True, report_file=None):
    """This method is entry point for ``buildtest cdash`` command which implements uploading
    results to CDASH server and command line interface to open CDASH project.

    Args:
        args (dict): Parsed arguments from `ArgumentParser.parse_args <https://docs.python.org/3/library/argparse.html#argparse.ArgumentParser.parse_args>`_
        default_configuration (buildtest.config.SiteConfiguration, optional): The loaded default configuration which is an instance of SiteConfiguration class
        open_browser (bool, optional): boolean to control if we open page in web browser using `webbrowser.open() <https://docs.python.org/3/library/webbrowser.html#webbrowser.open>`_. This is enabled by default, but can be turned off especially when running regression test where we don't want to see the page
    """

    # Shown below is an example cdash setting in configuration file
    #     cdash:
    #       url: https://my.cdash.org
    #       project: buildtest
    #       site: laptop
    configuration = default_configuration

    if not configuration.target_config:
        sys.exit("Unable to load a configuration file")

    cdash_config = deep_get(configuration.target_config, "cdash")

    if not cdash_config:
        sys.exit(
            f"We found no 'cdash' setting set in configuration file: {configuration.file}. Please specify 'cdash' setting in order to use 'buildtest cdash' command"
        )

    if args.cdash == "view":
        view_cdash_project(
            cdash_config=cdash_config,
            config_file=configuration.file,
            open_browser=open_browser,
        )

    if args.cdash == "upload":
        upload_test_cdash(
            build_name=args.buildname,
            configuration=configuration,
            site=args.site,
            report_file=report_file,
            open_browser=args.open,
        )


def view_cdash_project(cdash_config, config_file, open_browser=None):
    """Open CDASH project in browser which can be done by running ``buildtest cdash view``.
    Args:
        cdash_config (dict): Loaded CDASH configuration from configuration file
        config_file (str): Path to configuration file
        open_browser (bool, optional): Determine whether to open file in browser. This option is useful for regression check since we dont want to open file during a run
    """
    url = cdash_config["url"]
    project = cdash_config["project"]
    target_url = urljoin(url, f"index.php?project={project}")

    console.print("Opening URL:", target_url)
    # check for url via requests, it can raise an exception if its invalid URL in that case we print a message
    try:
        r = requests.get(target_url)
    except requests.ConnectionError as err:
        print(err)

        print(
            "\nShown below is the CDASH settings from configuration file:", config_file
        )
        print(yaml.dump(cdash_config, indent=2))
        sys.exit(f"Invalid URL: {target_url}")

    # A 200 status code is valid URL, if its not found we exit before opening page in browser
    if not r.status_code == 200:
        sys.exit("Invalid URL")

    if open_browser:
        webbrowser.open(target_url)


def upload_test_cdash(
    build_name, configuration, site=None, report_file=None, open_browser=None
):
    """This method is responsible for reading report file and pushing results to CDASH
    server. User can specify cdash settings in configuration file or pass them in command line.
    The command ``buildtest cdash upload`` will upload results to CDASH.

    Shown below is an example output. In this example **demo** is the build name that shows up in CDASH result.

    .. code-block:: console

        (buildtest)  ~/Documents/github/buildtest/ [buildtest_build*] buildtest cdash upload -o demo
        Reading report file:  /Users/siddiq90/Documents/github/buildtest/var/report.json
        Uploading 1 tests
        Build Name:  demo
        site:  generic
        MD5SUM: 02049fc1dad67acdeac79a4ffc24e553
        You can view the results at: https://my.cdash.org//viewTest.php?buildid=2181193

    Args:
        build_name (str): build name that shows up in CDASH
        configuration (buildtest.config.SiteConfiguration): Instance of SiteConfiguration class that contains the configuration file
        site (str, optional): Site name that shows up in CDASH
        report (str, optional): Path to report file when uploading results. This is specified via ``buildtest cdash upload -r`` command
        open_browser (str, optional): Open CDASH report in web browser. This is specified via ``buildtest cdash upload --open`` command
    """

    cdash_url = configuration.target_config["cdash"]["url"]
    site_name = site or configuration.target_config["cdash"]["site"]
    project_name = configuration.target_config["cdash"]["project"]

    if not build_name:
        sys.exit("Please specify a buildname")

    try:
        requests.get(cdash_url)
    except requests.ConnectionError:
        print(
            "\nShown below is the CDASH settings from configuration file:",
            configuration.file,
        )
        print(yaml.dump(configuration.target_config["cdash"], indent=2))
        console.print_exception()
        raise requests.ConnectionError

    upload_url = urljoin(cdash_url, f"submit.php?project={project_name}")

    r = requests.get(upload_url)
    # output of text property is the following:
    # '<cdash version="3.0.3">\n  <status>OK</status>\n  <message></message>\n  <md5>d41d8cd98f00b204e9800998ecf8427e</md5>\n</cdash>\n'
    if not re.search("<status>OK</status>", r.text):
        console.print("[red]Malformed XML, please check if project exist on CDASH!")
        sys.exit(f"Invalid URL: {upload_url}")

    # For best CDash results, builds names should be consistent (ie not change every time).

    input_datetime_format = "%Y/%m/%d %H:%M:%S"
    output_datetime_format = "%Y%m%d-%H%M"

    build_starttime = None
    build_endtime = None

    tests = []
    abspath_report_file = resolve_path(report_file) or BUILD_REPORT
    if not is_file(abspath_report_file):
        sys.exit(
            f"Unable to find report file: {abspath_report_file} please build a test via buildtest build"
        )

    print("Reading report file: ", abspath_report_file)

    with open(abspath_report_file) as json_file:
        buildtest_data = json.load(json_file)
        for buildspec in buildtest_data.keys():
            for test_name in buildtest_data[buildspec].keys():
                for test_data in buildtest_data[buildspec][test_name]:
                    # test_data = tests_data[0]

                    test = {}
                    # test["name"] = test_name + "/" + test_data["id"]
                    test["name"] = test_name
                    test["id"] = test_data["id"]

                    state = test_data["state"]
                    if state == "PASS":
                        test["status"] = "passed"
                    elif state == "FAIL":
                        test["status"] = "failed"
                    else:
                        print(
                            "Unrecognized state {0} for test {1}; marking it as failed".format(
                                state, test_name
                            )
                        )
                        test["status"] = "failed"
                    test["description"] = test_data["description"]
                    test["summary"] = test_data["summary"]
                    test["command"] = test_data["command"]
                    test["testpath"] = test_data["testpath"]
                    test["test_content"] = test_data["test_content"]
                    test["output"] = test_data["output"]
                    test["runtime"] = test_data["runtime"]
                    test["returncode"] = test_data["returncode"]
                    test["full_id"] = test_data["full_id"]
                    test["user"] = test_data["user"]
                    test["hostname"] = test_data["hostname"]
                    test["schemafile"] = test_data["schemafile"]
                    test["tags"] = test_data["tags"]
                    test["executor"] = test_data["executor"]
                    test["compiler"] = test_data["compiler"]
                    test["starttime"] = test_data["starttime"]
                    test["endtime"] = test_data["endtime"]
                    test["build_script"] = test_data["build_script"]
                    test["logpath"] = test_data["logpath"]
                    test["buildenv"] = test_data["buildenv"]
                    test["job"] = json.dumps(test_data["job"], indent=2, sort_keys=True)

                    # extra preformatted output fields
                    test["buildspec_content"] = test_data["buildspec_content"]
                    test["error"] = test_data["error"]
                    test["test_content"] = test_data["test_content"]
                    test["buildscript_content"] = test_data["buildscript_content"]
                    # metrics property must be converted to string inorder to push to cdash
                    test["metrics"] = json.dumps(
                        test_data["metrics"], indent=2, sort_keys=True
                    )

                    # tags == labels
                    test["tags"] = test_data["tags"]

                    test["testroot"] = test_data["testroot"]
                    test["stagedir"] = test_data["stagedir"]
                    test["outfile"] = test_data["outfile"]
                    test["errfile"] = test_data["errfile"]

                    # test start and end time.
                    starttime = test_data["starttime"]
                    test_starttime_datetime = datetime.strptime(
                        starttime, input_datetime_format
                    )
                    endtime = test_data["endtime"]
                    test_endtime_datetime = datetime.strptime(
                        endtime, input_datetime_format
                    )
                    if not build_starttime or build_starttime > test_starttime_datetime:
                        build_starttime = test_starttime_datetime
                    if not build_endtime or build_endtime < test_endtime_datetime:
                        build_endtime = test_endtime_datetime
                    tests.append(test)

                    # remove ANSI escape characters from output and error field to avoid issues with CDASH upload. See https://localcoder.org/how-can-i-remove-the-ansi-escape-sequences-from-a-string-in-python
                    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
                    ansi_escape.sub("", test["output"])
                    ansi_escape.sub("", test["error"])

    console.print(f"Uploading {len(tests)} tests")

    build_stamp = build_starttime.strftime(output_datetime_format)
    build_stamp += "-Experimental"

    filename = "Test.xml"
    site_element = ET.Element(
        "Site", Name=site_name, BuildName=build_name, BuildStamp=build_stamp
    )
    testing_element = ET.SubElement(site_element, "Testing")
    ET.SubElement(testing_element, "StartTestTime").text = str(
        round(datetime.timestamp(build_starttime))
    )
    ET.SubElement(testing_element, "EndTestTime").text = str(
        round(datetime.timestamp(build_endtime))
    )

    for test in tests:
        test_element = ET.SubElement(testing_element, "Test", Status=test["status"])
        # ET.SubElement(test_element, "id").text = test["id"]
        ET.SubElement(test_element, "Name").text = test["name"]
        ET.SubElement(test_element, "Description").text = test["description"]
        ET.SubElement(test_element, "FullCommandLine").text = test["command"]
        results_element = ET.SubElement(test_element, "Results")

        runtime_measurement = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="numeric/double",
            name="Execution Time",
        )
        ET.SubElement(runtime_measurement, "Value").text = str(test["runtime"])

        testid_measurement = ET.SubElement(
            results_element, "NamedMeasurement", type="text/string", name="Test ID"
        )
        ET.SubElement(testid_measurement, "Value").text = test["full_id"]

        returncode_measurement = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="numeric/double",
            name="Return Code",
        )
        ET.SubElement(returncode_measurement, "Value").text = str(test["returncode"])

        for field in [
            "user",
            "id",
            "hostname",
            "description",
            "command",
            "executor",
            "tags",
            "testroot",
            "stagedir",
            "build_script",
            "testpath",
            "outfile",
            "errfile",
            "buildenv",
            "starttime",
            "endtime",
            "logpath",
            "compiler",
            "schemafile",
        ]:
            measurement = ET.SubElement(
                results_element, "NamedMeasurement", type="text/string", name=field
            )
            ET.SubElement(measurement, "Value").text = test[field]

        summary_content = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="text/preformatted",
            name="Summary",
        )
        ET.SubElement(summary_content, "Value").text = test["summary"]

        error_content = ET.SubElement(
            results_element, "NamedMeasurement", type="text/preformatted", name="Error"
        )
        ET.SubElement(error_content, "Value").text = test["error"]

        buildspec_content = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="text/preformatted",
            name="Buildspec Content",
        )
        ET.SubElement(buildspec_content, "Value").text = test["buildspec_content"]

        test_content = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="text/preformatted",
            name="Test Content",
        )
        ET.SubElement(test_content, "Value").text = test["test_content"]

        build_script_content = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="text/preformatted",
            name="Build Script Content",
        )
        ET.SubElement(build_script_content, "Value").text = test["buildscript_content"]

        output_measurement = ET.SubElement(results_element, "Measurement")

        base64_zlib_output = base64.b64encode(
            zlib.compress(bytes("".join(test["output"]), "ascii"))
        ).decode("ascii")
        ET.SubElement(
            output_measurement, "Value", encoding="base64", compression="gzip"
        ).text = base64_zlib_output

        metrics = ET.SubElement(
            results_element,
            "NamedMeasurement",
            type="text/preformatted",
            name="Metrics",
        )
        ET.SubElement(metrics, "Value").text = test["metrics"]

        job = ET.SubElement(
            results_element, "NamedMeasurement", type="text/preformatted", name="Job"
        )
        ET.SubElement(job, "Value").text = test["job"]

        gitlab_job_url = os.getenv("CI_JOB_URL")
        if gitlab_job_url is not None:
            gitlab_link_measurement = ET.SubElement(
                results_element,
                "NamedMeasurement",
                type="text/link",
                name="View GitLab CI results",
            )
            ET.SubElement(gitlab_link_measurement, "Value").text = gitlab_job_url

        # Report tags as labels
        labels_element = ET.SubElement(test_element, "Labels")
        for tag in test["tags"].split(" "):
            ET.SubElement(labels_element, "Label").text = tag

    xml_tree = ET.ElementTree(site_element)
    xml_tree.write(filename)

    # Compute md5 checksum for the contents of this file.
    with open(filename) as xml_file:
        md5sum = hashlib.md5(xml_file.read().encode("utf-8")).hexdigest()

    buildid_regexp = re.compile("<buildId>([0-9]+)</buildId>")
    with open(filename, "rb") as fd:
        params_dict = {
            "build": build_name,
            "site": site_name,
            "stamp": build_stamp,
            "MD5": md5sum,
        }
        console.print("[red]Build Name: ", build_name)
        console.print("[green]site: ", site_name)
        console.print("[blue]MD5SUM:", md5sum)
        encoded_params = urlencode(params_dict)
        url = "{0}&{1}".format(upload_url, encoded_params)
        hdrs = {"Content-Type": "text/xml", "Content-Length": os.path.getsize(filename)}
        request = Request(url, data=fd, method="PUT", headers=hdrs)

        with urlopen(request) as response:
            resp_value = response.read()
            if isinstance(resp_value, bytes):
                resp_value = resp_value.decode("utf-8")
            match = buildid_regexp.search(resp_value)
            if match:
                buildid = match.group(1)
                url_view = f"{cdash_url}/viewTest.php?buildid={buildid}"
                console.print(f"You can view the results at: {url_view}")
                if open_browser:
                    webbrowser.open(url_view)

        os.remove(filename)
