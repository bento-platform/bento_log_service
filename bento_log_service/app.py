import bento_log_service
import os
import sys

from bento_lib.auth.flask_decorators import flask_permissions_owner
from bento_lib.responses.flask_errors import (
    flask_error_wrap,
    flask_error_wrap_with_traceback,
    flask_internal_server_error,
    flask_bad_request_error,
    flask_not_found_error,
)
from flask import Flask, json, jsonify, send_file
from urllib.parse import urljoin
from werkzeug.exceptions import BadRequest, NotFound


TIMEOUT = 1


SERVICE_ARTIFACT = "log-service"
SERVICE_TYPE = f"ca.c3g.bento:{SERVICE_ARTIFACT}:{bento_log_service.__version__}"
SERVICE_ID = os.environ.get("SERVICE_ID", SERVICE_TYPE)
SERVICE_NAME = "Bento Log Service"

SERVICE_INFO = {
    "id": SERVICE_ID,
    "name": SERVICE_NAME,  # TODO: Should be globally unique?
    "type": SERVICE_TYPE,
    "description": "Log-fetching microservice for a Bento platform node.",
    "organization": {
        "name": "C3G",
        "url": "http://www.computationalgenomics.ca"
    },
    "contactUrl": "mailto:david.lougheed@mail.mcgill.ca",
    "version": bento_log_service.__version__
}

CHORD_URL = os.environ.get("CHORD_URL", "http://127.0.0.1:5000/")  # Own node's URL
SERVICE_BASE_PATH = os.environ.get("SERVICE_URL_BASE_PATH", "/")

SERVICE_URL = urljoin(CHORD_URL, SERVICE_BASE_PATH)

CHORD_SERVICES_PATH = os.environ.get("CHORD_SERVICES", "chord_services.json")
with open(CHORD_SERVICES_PATH, "r") as f:
    CHORD_SERVICES = [s for s in json.load(f) if not s.get("disabled")]  # Skip disabled services

SERVICE_LOGS_TEMPLATE = "/chord/tmp/logs/{service_artifact}/"


application = Flask(__name__)
application.config.from_mapping(CHORD_SERVICES=CHORD_SERVICES_PATH)

# Generic catch-all
application.register_error_handler(Exception, flask_error_wrap_with_traceback(flask_internal_server_error,
                                                                              service_name=SERVICE_NAME))
application.register_error_handler(BadRequest, flask_error_wrap(flask_bad_request_error))
application.register_error_handler(NotFound, flask_error_wrap(flask_not_found_error))


SYSTEM_LOGS = [
    {
        "service": "nginx",
        "logs": {
            "access.log": "/chord/tmp/nginx/access.log",
            "error.log": "/chord/tmp/nginx/error.log",
        }
    },
    {
        "service": "redis",
        "logs": {
            "redis.log": "/chord/tmp/redis/"
        },
    }
]

SYSTEM_LOGS_DICT = {s["service"]: s for s in SYSTEM_LOGS}


def _get_service_files(service_artifact):
    (_, _, files) = next(os.walk(SERVICE_LOGS_TEMPLATE.format(service_artifact=service_artifact)), ((), (), ()))
    return files


SERVICE_LOGS = [
    {
        "service": s["type"]["artifact"],
        "logs": {
            os.path.basename(fp): fp
            for fp in _get_service_files(s["type"]["artifact"])
        },
    }
    for s in CHORD_SERVICES
]

SERVICE_LOGS_DICT = {s["service"]: s for s in SERVICE_LOGS}


def _log_to_endpoint_value(s, log_base_path: str):
    # TODO: Proper log URL
    return {
        **s,
        "logs": [{log: urljoin(SERVICE_URL, f"{log_base_path}/{s['service']}/{log}")} for log in s["logs"]]
    }


def _logs_endpoint(log_list, log_base_path: str):
    return jsonify([_log_to_endpoint_value(s, log_base_path) for s in log_list])


def _logs_service_endpoint(log_dict: dict, service: str, log_base_path: str):
    if not service or service not in log_dict:
        return flask_not_found_error(f"Could not find service '{service}'")

    return _log_to_endpoint_value(log_dict[service], log_base_path)


def _log_bytes_endpoint(log_dict: dict, service: str, log: str):
    if not service or service not in log_dict or not log or log not in log_dict[service]["logs"]:
        return application.response_class(status=404)

    file_path = log_dict[service]["logs"][log]

    try:
        return send_file(file_path, mimetype="text/plain", as_attachment=False)
    except FileNotFoundError:
        print(f"[{SERVICE_NAME}] [ERROR] Could not find file: '{file_path}'", flush=True, file=sys.stderr)
        return application.response_class(status=500)


@flask_permissions_owner
@application.route("/system-logs")
def system_logs():
    return _logs_endpoint(SYSTEM_LOGS, "system-logs")


@flask_permissions_owner
@application.route("/system-logs/<string:service>")
def system_service(service: str):
    return _logs_service_endpoint(SYSTEM_LOGS_DICT, service, "system-logs")


@flask_permissions_owner
@application.route("/system-logs/<string:service>/<string:log>")
def system_service_log(service: str, log: str):
    return _log_bytes_endpoint(SYSTEM_LOGS_DICT, service, log)


@flask_permissions_owner
@application.route("/service-logs")
def bento_logs():
    return _logs_endpoint(SERVICE_LOGS, "service-logs")


@flask_permissions_owner
@application.route("/service-logs/<string:service>")
def bento_service(service: str):
    return _logs_service_endpoint(SERVICE_LOGS_DICT, service, "service-logs")


@flask_permissions_owner
@application.route("/system-logs/<string:service>/<string:log>")
def bento_service_log(service: str, log: str):
    return _log_bytes_endpoint(SERVICE_LOGS_DICT, service, log)


@application.route("/service-info")
def service_info():
    # Spec: https://github.com/ga4gh-discovery/ga4gh-service-info
    return jsonify(SERVICE_INFO)
