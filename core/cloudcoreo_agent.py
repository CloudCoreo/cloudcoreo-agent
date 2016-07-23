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
import re
import requests
import stat
import sys
import yaml
from core import __version__

SQS_GET_MESSAGES_SLEEP_TIME = 10
SQS_VISIBILITY_TIMEOUT = 0
logging.basicConfig()
DEFAULT_CONFIG_FILE_LOCATION = '/etc/cloudcoreo/agent.conf'
# globals for caching
MY_AZ = None
version = '0.1.15'
COMPLETE_STRING = "COREO::BOOTSTRAP::complete"
OPTIONS_FROM_CONFIG_FILE = None
LOCK_FILE_PATH = ''
PIP_PACKAGE_NAME = 'run_client'
PROCESSED_SQS_MESSAGES_DICT_PATH = '/tmp/processed-messages.txt'
dt = time.time()
LOGS = [{'text': 'test', 'date': dt},
        {'text': 'test1', 'date': dt}]


def log(log_text):
    log_text = str(log_text)
    print log_text
    log_dict = {'text': log_text, 'date': time.time()}
    LOGS.append(log_dict)


def read_processed_messages_from_file():
    print PROCESSED_SQS_MESSAGES_DICT_PATH
    try:
        return eval(open(PROCESSED_SQS_MESSAGES_DICT_PATH, 'r').read())
    except Exception as ex:
        log(ex)
        return {}


def publish_to_sns(message_text, subject, topic_arn):
    sns_response = SNS_CLIENT.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=message_text
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


def get_configs(path):
    with open(path, 'r') as ymlfile:
        configs = yaml.load(ymlfile)
    return DotDict(configs)


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
    mkdir_p(work_dir)
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
    log("os.chdir(%s)" % work_dir)
    os.chdir(work_dir)
    log("cloning repo from url: %s" % repo_url.strip())
    git(ssh_wrapper_path, work_dir, "clone", repo_url.strip(), "repo")
    log("os.chdir(%s/repo)" % work_dir)
    os.chdir("%s/repo" % work_dir)

    if branch is not None:
        log("checking out branch %s" % branch)
        git(ssh_wrapper_path, "%s/repo" % work_dir, "checkout", branch)

    if revision is not None:
        log("checking out revision %s" % revision)
        git(ssh_wrapper_path, "%s/repo" % work_dir, "checkout", revision)

    log("completed recursive checkout")
    git(ssh_wrapper_path, "%s/repo" % work_dir, "submodule", "update", "--recursive", "--init")
    log("completed recursive checkout")


def get_config():
    config = get_coreo_appstackinstance_config()
    log("got config: %s" % config)
    return config


def get_default_config():
    config = get_coreo_appstack()
    log("got appstack: %s" % config)
    return config


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
    default_config = get_default_config()
    log("got default from appstack [%s]" % default_config)
    config = get_config()
    log("got config [%s]" % config)
    default_vars = json.loads(
        re.sub('\n', r'', unicodedata.normalize('NFKD', default_config['config']).encode('ascii', 'ignore')))
    instance_vars = json.loads(
        re.sub('\n', r'', unicodedata.normalize('NFKD', config['document']).encode('ascii', 'ignore')))
    all_vars = {'variables': default_vars['variables']}
    all_vars['variables'].update(instance_vars['variables'])
    for var in all_vars['variables']:
        value = all_vars['variables'][var]
        log("value: %s" % value)
        # if ! value['value'].nil? then
        if 'value' in value.keys() and value['value'] is not None:
            # environment[var.to_s] = value['value']
            environment[var] = value['value']
        else:
            # elsif ! value['default'].nil? then
            environment[var] = value.get('default', '')
    return environment


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
            log("checking if boot-scritsorder is in [%s]" % strings_replaced)
            if "boot-scriptsorder" in strings_replaced:
                order_files.append(full_path)
    if len(order_files) == 0 and server_name != "repo":
        order_files = get_script_order_files(root_dir, "repo")
    log("found ordered_files: %s" % order_files)
    order_files.sort(key=len, reverse=True)
    log("order_files %s" % order_files)
    return order_files


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


def run_cmd(work_dir, *args):
    print("cwd=%s" % work_dir)
    print("running command: %s" % str(list(args)))
    with open(OPTIONS_FROM_CONFIG_FILE.log_file, 'a') as log_file:
        proc_ret_code = subprocess.call(list(args),
                                        cwd=work_dir,
                                        shell=False,
                                        stdout=log_file,
                                        stderr=log_file)

    if proc_ret_code == 0:
        # return the return code
        log("Success running script [%s]" % list(args))
        log("  returning rc [%d]" % proc_ret_code)
        return None
    else:
        return proc_ret_code


def run_all_boot_scripts(repo_dir, server_name_dir):
    # env = {}
    env = get_environment_dict()
    # script_order_files = []
    script_order_files = get_script_order_files(repo_dir, server_name_dir)
    log("setting env [%s]" % env)

    full_run_error = None
    for f in script_order_files:
        log("loading file [%s]" % f)
        my_doc = yaml.load(open(f, "r"))
        log("got yaml doc [%s]" % my_doc)
        if my_doc is None or my_doc['script-order'] is None:
            continue
        log("[%s]" % my_doc['script-order'])
        # order = YAML.load_file(f)
        # order['script-order'].each { |script|
        for script in my_doc['script-order']:
            # full_path = File.join(File.dirname(f), script)
            full_path = os.path.join(os.path.dirname(f), script)
            log("running script [%s]" % full_path)
            os.chmod(full_path, stat.S_IEXEC)
            set_env(env)
            if full_path in open(LOCK_FILE_PATH, 'r').read():
                log("skipping run of [%s]. Already run" % script)
                continue
            # we need to check the error and output if we are debugging or not
            err = None
            out = None
            if not OPTIONS_FROM_CONFIG_FILE.debug:
                err = run_cmd(os.path.dirname(full_path), "./%s" % os.path.basename(full_path))
            if not err:
                with open(LOCK_FILE_PATH, 'a') as lockFile:
                    lockFile.write("%s\n" % full_path)
            else:
                full_run_error = err
                log(err)
            log(out)

    # if we have not received any errors for the whole run, lets mark the bootstrap lock as complete
    if not full_run_error:
        with open(LOCK_FILE_PATH, 'a') as lockFile:
            lockFile.write(COMPLETE_STRING)


def bootstrap():
    #  asi = get_coreo_appstackinstance_response("")
    log("getting response from server")
    asi = get_coreo_appstackinstance()
    appstack = get_coreo_appstack()
    key = get_coreo_key()
    #  Coreo::GIT.clone_for_asi("#{DaemonKit.arguments.options[:asi_id]}", asi['branch'], asi['revision'],
    # asi['gitUrl'], asi['keyMaterial'], "#{DaemonKit.arguments.options[:work_dir]}")
    clone_for_asi(asi['branch'], asi['revision'], appstack['gitUrl'], key['keyMaterial'],
                  OPTIONS_FROM_CONFIG_FILE.work_dir)
    #  run_all_boot_scripts("#{DaemonKit.arguments.options[:work_dir]}", "#{DaemonKit.arguments.options[:server_name]}")
    run_all_boot_scripts(OPTIONS_FROM_CONFIG_FILE.work_dir, OPTIONS_FROM_CONFIG_FILE.serverName)


def send_logs_to_webapp():
    message_with_logs_for_webapp = {
        "body": LOGS
    }
    stringified_json = json.dumps(message_with_logs_for_webapp)
    try:
        publish_to_sns(stringified_json, 'LOGS', OPTIONS_FROM_CONFIG_FILE.topic_arn)
        del LOGS[:]
    except Exception as ex:
        log(ex)


def process_incoming_sqs_messages(sqs_response):
    sqs_messages = sqs_response[u'Messages']
    if len(sqs_messages):
        # TODO investigate how does it work
        os.environ['AWS_ACCESS_KEY_ID'] = OPTIONS_FROM_CONFIG_FILE['coreo_access_id']
        os.environ['AWS_SECRET_ACCESS_KEY'] = OPTIONS_FROM_CONFIG_FILE['coreo_access_key']
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
        script = message_body['payload']
        if not OPTIONS_FROM_CONFIG_FILE.debug:
            os.chmod(script, stat.S_IEXEC)
            os.system(script)
    except Exception as ex:
        log("exception: %s" % str(ex))


# TODO add PROCESSED_SQS_MESSAGES clearness


def recursive_daemon():
    try:
        # if not os.path.isfile(LOCK_FILE_PATH):
        #     # touch the bootstrap lock file to indicate we have started to run through it
        #     with open(LOCK_FILE_PATH, 'a'):
        #         os.utime(LOCK_FILE_PATH, None)
        # if COMPLETE_STRING not in open(LOCK_FILE_PATH, 'r').read():
        #     bootstrap()
        sqs_response = get_sqs_messages(OPTIONS_FROM_CONFIG_FILE.queue_url)
        if not sqs_response:
            raise ValueError("Error while getting SQS messages.")
        if u'Messages' in sqs_response:
            process_incoming_sqs_messages(sqs_response)
        if len(LOGS):
            send_logs_to_webapp()
    except Exception as ex:
        log("Exception caught: [%s]" % str(ex))
        log(traceback.format_exc())
        if OPTIONS_FROM_CONFIG_FILE.debug:
            terminate_script()
            # TODO may be we need to add some time.sleep before restarting a loop?
    finally:
        recursive_daemon()


def start_agent():
    print '*Starting agent... Version ' + __version__
    config_file_location = get_config_path()
    print '*Reading configs from ' + config_file_location
    global OPTIONS_FROM_CONFIG_FILE
    OPTIONS_FROM_CONFIG_FILE = get_configs(config_file_location)

    # lets set up a lock file so we don't rerun on bootstrap... this will
    # also allow people to remove the lock file to rerun everything
    global LOCK_FILE_PATH
    LOCK_FILE_PATH = "%s/bootstrap.lock" % OPTIONS_FROM_CONFIG_FILE.work_dir

    if OPTIONS_FROM_CONFIG_FILE.version:
        print "%s" % version
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

    PROCESSED_SQS_MESSAGES = read_processed_messages_from_file()
    print PROCESSED_SQS_MESSAGES

    recursive_daemon()

parser=argparse.ArgumentParser(description='Parse version argument')
parser.add_argument('--version', action='store_true', help="Get script version")
if parser.parse_args().version:
    print "%s" % version
    terminate_script()

start_agent()
