#!/usr/bin/env python
######################################################################
# Cloudcoreo client
#
######################################################################
import time
import boto3
import json
import logging
import string
import traceback
import unicodedata
import subprocess
import argparse
from tempfile import mkstemp

import os
import shutil
import uuid
import re
import requests
import stat
import sys
import yaml
import socket
from core import __version__

SQS_GET_MESSAGES_SLEEP_TIME = 10
SQS_VISIBILITY_TIMEOUT = 0
SNS_CLIENT = None
SQS_CLIENT = None
logging.basicConfig()
DEFAULT_CONFIG_FILE_LOCATION = '/etc/cloudcoreo/agent.conf'
# globals for caching
MY_AZ = None
COMPLETE_STRING = "COREO::BOOTSTRAP::complete"
SENT_OP_SCRIPTS_STRING = "COREO::BOOTSTRAP::opscripts_sent"
OPTIONS_FROM_CONFIG_FILE = None
LOCK_FILE_PATH = ''
PIP_PACKAGE_NAME = 'run_client'
PROCESSED_SQS_MESSAGES_DICT_PATH = '/tmp/processed-messages.txt'
dt = time.time()
LOGS = []
MESSAGE_NEXT_NONE = -1
MAX_EXCEPTION_WAIT_DELAY = 60
HEARTBEAT_INTERVAL = 120
PROCESSED_SQS_MESSAGES = {}

# sort directories by extends, stack-, overrides, services, shutdown-, boot-, operational-
PRECEDENCE_ORDER = {'t': 0, 'e': 1, 's': 2, 'p': 3, 'v': 4, 'o': 5, 'b': 6}


def log(log_text):
    log_text = str(log_text)
    print log_text
    log_dict = {'log_message': log_text, 'date': time.time()}
    LOGS.append(log_dict)


def read_processed_messages_from_file():
    print PROCESSED_SQS_MESSAGES_DICT_PATH
    try:
        return eval(open(PROCESSED_SQS_MESSAGES_DICT_PATH, 'r').read())
    except Exception as ex:
        log(ex)
        return {}


def publish_to_sns(message_text, subject, topic_arn):
    if not OPTIONS_FROM_CONFIG_FILE.debug:
        sns_response = SNS_CLIENT.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=json.dumps(message_text)
        )
        return sns_response


def get_sqs_messages(queue_url):
    response = SQS_CLIENT.receive_message(
        QueueUrl=queue_url,
        VisibilityTimeout=SQS_VISIBILITY_TIMEOUT,
        WaitTimeSeconds=20
    )
    return response


class DotDict(dict):
    """dot.notation access to dictionary attributes"""

    def __getattr__(self, attr):
        return self.get(attr)

    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def get_config_path():
    parser = argparse.ArgumentParser(description='Get config file path')
    parser.add_argument('--config', help="Set config file location")
    config_file_location_from_console = parser.parse_args().config
    config_file_location = config_file_location_from_console or DEFAULT_CONFIG_FILE_LOCATION
    return config_file_location


def get_configs(conffile=''):
    config_file_location = get_config_path()
    if conffile:
        config_file_location = conffile
    print '*Reading configs from ' + config_file_location
    with open(config_file_location, 'r') as ymlfile:
        configs = yaml.load(ymlfile)
    return DotDict(configs)


def set_agent_uuid():
    config_file_location = get_config_path()
    with open(config_file_location, 'r') as ymlfile:
        configs = yaml.load(ymlfile)

    # Save agent_uuid to config file
    with open(config_file_location, 'w') as ymlfile:
        agent_uuid = uuid.uuid1()
        configs['agent_uuid'] = str(agent_uuid)
        ymlfile.write(yaml.dump(configs, default_style="'"))

    global OPTIONS_FROM_CONFIG_FILE
    OPTIONS_FROM_CONFIG_FILE = get_configs()
    log("OPTIONS.agent_uuid: %s" % OPTIONS_FROM_CONFIG_FILE.agent_uuid)


def create_message_template(message_type, data):
    message = {
        "header": {
            "publisher": {
                "publisher_type": "agent",
                "publisher_version": __version__,
                "publisher_id": OPTIONS_FROM_CONFIG_FILE.agent_uuid,
                "publisher_access_id": OPTIONS_FROM_CONFIG_FILE.coreo_access_id
            },
        },
        "body": {
            "timestamp": time.time(),
            "message_type": message_type,
            "data": data
        }
    }
    return message


def publish_agent_logs():
    message_with_logs_for_webapp = create_message_template("SCRIPT_LOGS", LOGS)
    try:
        publish_to_sns(message_with_logs_for_webapp, 'AGENT_LOGS', OPTIONS_FROM_CONFIG_FILE.topic_arn)
        del LOGS[:]
    except Exception as ex:
        log(ex)


def publish_agent_online():
    message_data = {
        "server_name": OPTIONS_FROM_CONFIG_FILE.server_name,
        "namespace": OPTIONS_FROM_CONFIG_FILE.namespace,
        "run_id": OPTIONS_FROM_CONFIG_FILE.run_id,
        "hostname": socket.gethostname()
    }
    message = create_message_template("AGENT_ONLINE", message_data)
    publish_to_sns(message, 'AGENT_INFO', OPTIONS_FROM_CONFIG_FILE.topic_arn)


def publish_agent_heartbeat():
    message_data = {
        "load": json.dumps(os.getloadavg())
    }
    message = create_message_template("AGENT_HEARTBEAT", message_data)
    publish_to_sns(message, 'AGENT_INFO', OPTIONS_FROM_CONFIG_FILE.topic_arn)


def publish_script_result(script_name, script_return_code):
    message_data = {
        "script_name": script_name,
        "return_code": script_return_code
    }
    message = create_message_template("SCRIPT_RESULT", message_data)
    publish_to_sns(message, 'AGENT_INFO', OPTIONS_FROM_CONFIG_FILE.topic_arn)


def publish_op_scripts(repo_dir, server_name):
    if SENT_OP_SCRIPTS_STRING in open(LOCK_FILE_PATH, 'r').read():
        log("already sent operational scripts")
        return

    op_scripts = collect_operational_scripts(repo_dir, server_name)
    # remove path from scripts
    message_data = [os.path.basename(test_file) for test_file in op_scripts]
    message = create_message_template("OP_SCRIPTS", message_data)
    publish_to_sns(message, 'AGENT_INFO', OPTIONS_FROM_CONFIG_FILE.topic_arn)

    with open(LOCK_FILE_PATH, 'a') as lockFile:
        lockFile.write("%s\n" % SENT_OP_SCRIPTS_STRING)


def collect_operational_scripts(repo_dir, server_name):
    # Collect operational scripts
    override = False
    op_scripts = precedence_walk(repo_dir, "operational-scripts", server_name, override)
    return [test_file for test_file in op_scripts if ".sh" in test_file]


def get_availability_zone():
    # cached
    global MY_AZ
    if MY_AZ is None:
        if OPTIONS_FROM_CONFIG_FILE.debug:
            MY_AZ = 'us-east-1a'
        else:
            MY_AZ = meta_data("placement/availability-zone")
    return MY_AZ


def get_region():
    region = get_availability_zone()[:-1]
    log("region: %s" % region)
    return region


def meta_data(data_path):
    # using 169.254.169.254 instead of 'instance-data' because some people
    # like to modify their dhcp tables...
    return requests.get('http://169.254.169.254/latest/meta-data/%s' % data_path).text


def get_coreo_key():
    content = open("%s/git_key.out" % OPTIONS_FROM_CONFIG_FILE.work_dir, 'r').read()
    return json.loads(content)


def get_coreo_appstack():
    content = open("%s/appstack.out" % OPTIONS_FROM_CONFIG_FILE.work_dir, 'r').read()
    return json.loads(content)


def get_coreo_appstackinstance_config():
    content = open("%s/appstack_instance_config.out" % OPTIONS_FROM_CONFIG_FILE.work_dir, 'r').read()
    return json.loads(content)


def get_coreo_appstackinstance():
    content = open("%s/appstack_instance.out" % OPTIONS_FROM_CONFIG_FILE.work_dir, 'r').read()
    return json.loads(content)


def mkdir_p(path):
    if not os.path.exists(path):
        log("creating path [%s]" % path)
        os.makedirs(path)
        log("created path [%s]" % path)


def clone_for_asi(branch, revision, repo_url, key_material, work_dir):
    gitError = False

    if repo_url.strip() in open(LOCK_FILE_PATH, 'r').read():
        log("skipping git clone for repo [%s]. Already cloned." % repo_url.strip())
        return gitError

    fd, temp_key_path = mkstemp()

    # lets write the private key material to a temp file
    # this creates a file in the most secure way possible
    # so no chmod is necessary
    pkey = open(temp_key_path, 'w')
    log("writing private key material to %s" % temp_key_path)
    pkey.write(key_material)
    pkey.close()
    os.close(fd)

    # now we need to have the public key there as well
    # p = subprocess.Popen(['ssh-keygen', '-y', '-f', temp_key_path, '>', "%s.pub" % temp_key_path],
    #                      stdin=subprocess.PIPE,
    #                      stdout=subprocess.PIPE,
    #                      stderr=subprocess.PIPE,
    #                      preexec_fn=os.setsid
    #                      )

    # now we set up the git-ssh wrapper script
    fd_ssh, ssh_wrapper_path = mkstemp()
    log("writing ssh wrapper script to %s" % ssh_wrapper_path)
    wrap = open(ssh_wrapper_path, 'w')
    wrap.write("""#!/bin/sh
/usr/bin/ssh -o StrictHostKeyChecking=no -i "%s" "$@" 
    """ % temp_key_path)
    wrap.close()
    os.close(fd_ssh)
    st = os.stat(ssh_wrapper_path)
    os.chmod(ssh_wrapper_path, st.st_mode | stat.S_IEXEC)

    # now we do the cloning
    mkdir_p(work_dir)
    log("os.chdir(%s)" % work_dir)
    os.chdir(work_dir)
    log("cloning repo from url: %s" % repo_url.strip())
    process = git(ssh_wrapper_path, work_dir, "clone", repo_url.strip(), "repo")
    log("git clone returned: %s" % process.returncode)
    if process.returncode != 0:
        gitError = True
    log("os.chdir(%s/repo)" % work_dir)
    os.chdir("%s/repo" % work_dir)

    if branch is not None:
        log("checking out branch %s" % branch)
        process = git(ssh_wrapper_path, "%s/repo" % work_dir, "checkout", branch)
        log("git checkout branch returned: %s" % process.returncode)
        if process.returncode != 0:
            gitError = True

    if revision is not None:
        log("checking out revision %s" % revision)
        process = git(ssh_wrapper_path, "%s/repo" % work_dir, "checkout", revision)
        log("git checkout revision returned: %s" % process.returncode)
        if process.returncode != 0:
            gitError = True

    log("starting recursive checkout")
    process = git(ssh_wrapper_path, "%s/repo" % work_dir, "submodule", "update", "--recursive", "--init")
    log("git submodule checkout returned: %s" % process.returncode)
    if process.returncode != 0:
        gitError = True
    log("completed recursive checkout")

    log("removing temporary files for git operations")
    os.remove(temp_key_path)
    os.remove(ssh_wrapper_path)

    # If all git operations succeeded, mark that repo was cloned successfully
    if not gitError:
        with open(LOCK_FILE_PATH, 'a') as lockFile:
            lockFile.write("%s\n" % repo_url.strip())

    return gitError

def git(ssh_wrapper, git_dir, *args):
    log("setting environment GIT_SSH=%s" % ssh_wrapper)
    os.environ['GIT_SSH'] = "%s" % ssh_wrapper
    log("cwd=%s" % git_dir)
    log("running command: %s" % str(['git'] + list(args)))
    p = subprocess.Popen(['git'] + list(args),
                         cwd=git_dir,
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         preexec_fn=os.setsid,
                         shell=False
                         )
    (std_out_data, std_err_data) = p.communicate()
    log("(std_out_data, std_err_data) = (%s, %s)" % (std_out_data, std_err_data))
    return p


def get_environment_dict():
    environment = {}
    asi_vars = get_coreo_appstackinstance_config()
    all_vars = {'variables': asi_vars}
    for var in all_vars['variables']:
        value = all_vars['variables'][var]
        # if ! value['value'].nil? then
        if 'value' in value.keys() and value['value'] is not None:
            # environment[var.to_s] = value['value']
            environment[var] = value['value']
        else:
            # elsif ! value['default'].nil? then
            environment[var] = value.get('default', '')
    return environment


## <DEPRECATED_CODE>
## PLA-513 deprecates get_script_order_files
## This code should remain here for backwards compatibility testing
######################################################################
# this is all to deal with overriding service config.rb files
######################################################################
def get_script_order_files(root_dir, server_name):
    order_files = []
    log("walking rootDir: %s" % root_dir)
    for dir_name, subdir_list, file_list in os.walk(root_dir):
        if ".git" in dir_name:
            continue
        for file_name in file_list:
            full_path = "%s/%s" % (dir_name, file_name)
            log("checking file [%s]" % full_path)
            log("checking if server_name [%s] is in full_path" % (server_name.lower()))
            if server_name.lower() not in full_path.lower():
                continue
            strings_replaced = string.replace(
                string.replace(string.replace(full_path.lower(), "extends", ""), "#{server_name.downcase}", ""), "/",
                "")
            log("checking if boot-scriptsorder is in [%s]" % strings_replaced)
            if "boot-scriptsorder" in strings_replaced:
                order_files.append(full_path)
    if len(order_files) == 0 and server_name != "repo":
        order_files = get_script_order_files(root_dir, "repo")
    log("found ordered_files: %s" % order_files)
    order_files.sort(key=len, reverse=True)
    log("order_files %s" % order_files)
    return order_files
## </DEPRECATED_CODE>


def precedence_walk(start_dir, look_for, stackdash="", override=False, debug=False):
    collected = []
    walk_params = next(os.walk(start_dir, topdown=True))
    for dirname in sorted(walk_params[1], key=lambda word: [PRECEDENCE_ORDER.get(c, ord(c)) for c in word]):
        full_path = os.path.join(start_dir, dirname)
        debug_path = re.sub('.*/repo', 'repo', start_dir)
        if ".git" in dirname:
            if debug: log("skipping git directory %s/%s : git" % (debug_path, dirname))
            continue
        elif "extends" in dirname:
            if debug: log("got %s/%s : extends" % (debug_path, dirname))
            collected.extend(precedence_walk(full_path, look_for, stackdash, override, debug))
        elif "stack-" in dirname:
            if debug: log("got %s/%s : stack-" % (debug_path, dirname))
            collected.extend(precedence_walk(full_path, look_for, stackdash, override, debug))
        elif "overrides" in dirname and override:
            if debug: log("got %s/%s : overrides" % (debug_path, dirname))
            collected.extend(precedence_walk(full_path, look_for, stackdash, override, debug))
        elif override:
            if debug: log("got %s/%s : any directory for override" % (debug_path, dirname))
            collected.extend(precedence_walk(full_path, look_for, stackdash, override, debug))
        if debug:
            if "services" in dirname:
                log("got %s/%s : services" % (debug_path, dirname))
            elif "boot-scripts" in dirname:
                log("got %s/%s : boot-scripts" % (debug_path, dirname))
            elif "operational-scripts" in dirname:
                log("got %s/%s : operational-scripts" % (debug_path, dirname))
            elif "shutdown-scripts" in dirname:
                log("got %s/%s : shutdown-scripts" % (debug_path, dirname))

        for filename in os.listdir(full_path):
            debug_path = re.sub('.*/repo', 'repo', full_path)
            if debug:
                log("considering filename: %s/%s" % (debug_path, filename))
            full_path_filename = os.path.join(full_path, filename)
            # Only consider files, not directories
            if not os.path.isfile(full_path_filename):
                if debug:
                    log("not a file: %s/%s" % (debug_path, filename))
                continue
            contains = look_for in full_path_filename and stackdash in full_path_filename
            if override and contains and "overrides" in full_path_filename:
                collected.append(full_path_filename)
                # Just replace first instance of overrides to do the copy
                dest = re.sub("overrides", "", full_path_filename, 1)
                if not os.path.isfile(dest):
                    dest = os.path.dirname(dest)
                    if not os.path.isdir(dest):
                        if debug: log("creating directory: %s" % re.sub('.*/repo', 'repo', dest))
                        os.makedirs(dest)
                shutil.copy(full_path_filename, dest)
                if debug:
                    command = "cp %s %s" % (re.sub('.*/repo', 'repo', full_path_filename), re.sub('.*/repo', 'repo', dest))
                    log("---> command: %s" % command)
            elif not override and contains:
                if debug: log("collecting file: %s" % full_path_filename)
                collected.append(full_path_filename)
            elif debug:
                log("skipping file: %s/%s" % (debug_path, filename))

    return collected


def set_env(env_list):
    for (key, val) in env_list.items():
        log("os.environ[%s] = %s" % (key, str(val)))
        os.environ[key] = str(val).strip().strip('"')

    # the order matters here - the env.out has to be last
    with open("%s/env.out" % OPTIONS_FROM_CONFIG_FILE.work_dir) as f:
        for line in f:
            values = line.split('=')
            if len(values) == 2:
                log("os.environ[%s] = %s" % (values[0], values[1]))
                os.environ[values[0]] = str(values[1]).strip().strip('"')


def run_cmd(full_script_path, environment):
    log("running script [%s]" % full_script_path)
    if OPTIONS_FROM_CONFIG_FILE.debug:
        command = "date"
    else:
        os.chmod(full_script_path, stat.S_IEXEC)
        command = "./%s" % os.path.basename(full_script_path)

    set_env(environment)

    work_dir = os.path.dirname(full_script_path)
    log("running command: %s" % command)
    log("cwd=%s" % work_dir)

    proc = subprocess.Popen(
        command,
        cwd=work_dir,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)

    (proc_stdout, proc_stderr) = proc.communicate()
    proc_ret_code = proc.returncode

    with open(OPTIONS_FROM_CONFIG_FILE.log_file, 'a') as log_file:
        log_file.write(proc_stdout)

    if proc_ret_code == 0:
        log("Success running script [%s]" % command)
    else:
        log("Error running script [%s]" % command)

    log("  script return code: [%d]" % proc_ret_code)

    log("  --- begin stdout ---")
    if proc_stdout:
        log(proc_stdout)
    log("  --- end stdout ---")
    log("  --- begin stderr ---")
    if proc_stderr:
        log(proc_stderr)
    log("  --- end stderr ---")

    publish_script_result(os.path.basename(command), proc_ret_code)
    publish_agent_logs()

    return proc_ret_code


def run_all_boot_scripts(repo_dir, server_name_dir):
    env = get_environment_dict()
    log("setting env [%s]" % env)

    # PLA-513 changes the method used to get files
    # script_order_files = get_script_order_files(repo_dir, server_name_dir)
    bootscripts_name = "boot-scripts/order.yaml"
    # Get the scripts to run assuming that overrides have already been applied earlier
    override = False
    script_order_files = precedence_walk(repo_dir, bootscripts_name, server_name_dir, override)

    num_order_files_processed = 0
    full_run_error = None
    for f in script_order_files:
        log("loading file [%s]" % f)
        my_doc = yaml.load(open(f, "r"))
        log("got yaml doc [%s]" % my_doc)
        if my_doc is None or my_doc['script-order'] is None:
            continue
        log("[%s]" % my_doc['script-order'])
        num_order_files_processed += 1
        for script in my_doc['script-order']:
            full_path = os.path.join(os.path.dirname(f), script)
            if full_path in open(LOCK_FILE_PATH, 'r').read():
                log("skipping run of [%s]. Already run" % script)
                continue

            err = run_cmd(full_path, env)
            if not err:
                with open(LOCK_FILE_PATH, 'a') as lockFile:
                    lockFile.write("%s\n" % full_path)
            else:
                full_run_error = err

    # if we have not received any errors for the whole run, lets mark the bootstrap lock as complete
    if not full_run_error:
        with open(LOCK_FILE_PATH, 'a') as lockFile:
            lockFile.write(COMPLETE_STRING)

    return num_order_files_processed


def get_server_name():
    server_name = OPTIONS_FROM_CONFIG_FILE.server_name
    # if we have no layered server, use repo/.
    if server_name == OPTIONS_FROM_CONFIG_FILE.namespace.replace('ROOT::', '').lower():
        server_name = ""

    return server_name


def bootstrap():
    log("getting response from server")
    asi = get_coreo_appstackinstance()
    appstack = get_coreo_appstack()
    key = get_coreo_key()
    clone_for_asi(asi['branch'], asi['revision'], appstack['gitUrl'], key['keyMaterial'],
                  OPTIONS_FROM_CONFIG_FILE.work_dir)

    # First apply any overrides in the repo for all files
    repo_dir = os.path.join(OPTIONS_FROM_CONFIG_FILE.work_dir, "repo")
    override = True
    precedence_walk(repo_dir, "", "", override)

    server_name = get_server_name()

    publish_op_scripts(repo_dir, server_name)

    # This should be last in bootstrap() because if no errors, the bootstrap file is marked completed
    run_all_boot_scripts(repo_dir, server_name)


def process_incoming_sqs_messages(sqs_response):
    sqs_messages = sqs_response[u'Messages']
    if len(sqs_messages):
        for message in sqs_messages:
            process_message(message)


def process_message(message):
    message_id = message[u'MessageId']
    if message_id not in PROCESSED_SQS_MESSAGES:
        PROCESSED_SQS_MESSAGES[message_id] = time.time()
        message_body = json.loads(message[u'Body'])
        print 'Got message via SQS'
        message_type = message_body['type']
        print 'Message type is ' + message_type
        if message_type.lower() == 'runcommand':
            run_script(message_body)
        elif message_type.lower() == u'update':
            try:
                open(PROCESSED_SQS_MESSAGES_DICT_PATH, 'w+').write(str(PROCESSED_SQS_MESSAGES))
                update_package()
                run_packet_start_command()
                terminate_script()
            except Exception as ex:
                log(ex)
        else:
            log("unknown message type" + message_type)
            # SQS_CLIENT.delete_message(
            #     QueueUrl=OPTIONS_FROM_CONFIG_FILE.queue_url,
            #     ReceiptHandle=first_sqs_message['ReceiptHandle']
            # )


def terminate_script():
    sys.exit(0)


def run_packet_start_command():
    subprocess.call([PIP_PACKAGE_NAME] + sys.argv[1:], shell=False)


def update_package():
    subprocess.call(['pip', 'install', '--upgrade', 'git+git://' + OPTIONS_FROM_CONFIG_FILE.agent_git_url])


def run_script(message_body):
    try:
        script_name = message_body['payload']
        repo_dir = os.path.join(OPTIONS_FROM_CONFIG_FILE.work_dir, "repo")
        server_name = get_server_name()
        op_scripts = collect_operational_scripts(repo_dir, server_name)
        full_script_path = [test_file for test_file in op_scripts if script_name in test_file]
        # assuming we only have a single script named script_name in full_script_path, so use [0]
        if len(full_script_path) and len(full_script_path[0]):
            env = get_environment_dict()
            run_cmd(full_script_path[0], env)
    except Exception as ex:
        log("exception: %s" % str(ex))


def main_loop():
    delay = 1
    start = time.time()
    while True:
        try:
            if not os.path.isfile(LOCK_FILE_PATH):
                # touch the bootstrap lock file to indicate we have started to run through it
                with open(LOCK_FILE_PATH, 'a'):
                    os.utime(LOCK_FILE_PATH, None)
            if COMPLETE_STRING not in open(LOCK_FILE_PATH, 'r').read():
                bootstrap()

            sqs_response = get_sqs_messages(OPTIONS_FROM_CONFIG_FILE.queue_url)
            if not sqs_response:
                raise ValueError("Error while getting SQS messages.")
            if u'Messages' in sqs_response:
                process_incoming_sqs_messages(sqs_response)
            if len(LOGS):
                publish_agent_logs()

            if time.time() - start > HEARTBEAT_INTERVAL:
                publish_agent_heartbeat()

            # success!
            delay = 1
        except Exception as ex:
            log("Exception caught: [%s]" % str(ex))
            log(traceback.format_exc())
            # double the delay up to max
            if delay < MAX_EXCEPTION_WAIT_DELAY:
                delay *= 2
            if OPTIONS_FROM_CONFIG_FILE.debug:
                terminate_script()

        time.sleep(delay)


def load_configs(conffile=''):
    global OPTIONS_FROM_CONFIG_FILE
    OPTIONS_FROM_CONFIG_FILE = get_configs(conffile)

    # lets set up a lock file so we don't rerun on bootstrap... this will
    # also allow people to remove the lock file to rerun everything
    global LOCK_FILE_PATH
    LOCK_FILE_PATH = "%s/bootstrap.lock" % OPTIONS_FROM_CONFIG_FILE.work_dir


def start_agent():
    print '*Starting agent... Version ' + __version__

    load_configs()
    if OPTIONS_FROM_CONFIG_FILE.version:
        print "%s" % __version__
        terminate_script()

    global SQS_CLIENT, SNS_CLIENT

    sqs_sns_region = OPTIONS_FROM_CONFIG_FILE.topic_arn.split(':')[3]
    log("SQS/SNS region from topic ARN: %s" % sqs_sns_region)
    aws_access_id = OPTIONS_FROM_CONFIG_FILE.coreo_access_id
    aws_secret_access_key = OPTIONS_FROM_CONFIG_FILE.coreo_access_key
    SQS_CLIENT = boto3.client('sqs',
                              aws_access_key_id='%s' % aws_access_id,
                              aws_secret_access_key='%s' % aws_secret_access_key,
                              region_name='%s' % sqs_sns_region)
    SNS_CLIENT = boto3.client('sns',
                              aws_access_key_id='%s' % aws_access_id,
                              aws_secret_access_key='%s' % aws_secret_access_key,
                              region_name='%s' % sqs_sns_region)

    if not OPTIONS_FROM_CONFIG_FILE.agent_uuid:
        set_agent_uuid()

    publish_agent_online()

    global PROCESSED_SQS_MESSAGES
    PROCESSED_SQS_MESSAGES = read_processed_messages_from_file()
    print PROCESSED_SQS_MESSAGES

    main_loop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parse version argument')
    parser.add_argument('--version', action='store_true', help="Get script version")
    if parser.parse_args().version:
        print "%s" % __version__
        terminate_script()

    start_agent()
