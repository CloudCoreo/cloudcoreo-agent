import subprocess
import os
import time


def print_output(rc, stdo, stde):
    print "proc_ret_code: %s" % rc
    if stdo:
        print "  --- begin stdout ---"
        print stdo
        print "  --- end stdout ---"
    if stde:
        print "  --- begin stderr ---"
        print stde
        print "  --- end stderr ---"


def run_cmd(full_script_path):
    work_dir = os.path.dirname(full_script_path)
    command = "./%s" % os.path.basename(full_script_path)
    print "running command: %s" % command
    print "cwd=%s" % work_dir

    runmode="file"

    if runmode == "communicate":
        ios = subprocess.PIPE
        proc = subprocess.Popen(
            command,
            cwd=work_dir,
            shell=False,
            stdin=ios,
            stdout=ios,
            stderr=ios)

        (proc_stdout, proc_stderr) = proc.communicate()
        proc_ret_code = proc.returncode
        print_output(proc_ret_code, proc_stdout, proc_stderr)
    elif runmode == "poll":
        ios = subprocess.PIPE
        # ios = None
        proc = subprocess.Popen(
            command,
            cwd=work_dir,
            shell=False,
            stdin=ios,
            stdout=ios,
            stderr=ios)

        # proc_pid = proc.pid
        #
        # print "got pid: %d" % proc_pid

        rc = None
        count = 0
        while rc is None and count < 10:
            rc = proc.poll()
            if rc is not None:
                break
            count += 1
            time.sleep(1)

        print "wait time for poll: %d" % count
        print "poll returns: %s" % rc

        (proc_stdout, proc_stderr) = proc.communicate()
        print_output(rc, proc_stdout, proc_stderr)
    elif runmode == "file":
        log_filename = "/tmp/%s.log" % os.path.basename(command)
        if os.path.exists(log_filename):
            os.remove(log_filename)
        with open(log_filename, 'w+') as log_file:
            proc = subprocess.Popen(
                command,
                cwd=work_dir,
                shell=False,
                stdout=log_file,
                stderr=log_file)
            count = 0
            where = log_file.tell()
            while proc.poll() is None:
                count += 1
                if count % 50 == 0:
                    count = 0
                    print "------ still waiting for pid: %d, where: %d" % (proc.pid, where)
                    log_file.seek(where)
                    for line in log_file:
                        print line
                        where = log_file.tell()

                time.sleep(.1)

        print "----- return code: %s" % proc.returncode

        with open(log_filename, 'r') as log_file:
            log_file.seek(where)
            for line in log_file:
                print line


print "------------ starting test -------------"
# sleeper.sh will never return...
# run_cmd("testdata/sleeper.sh")
run_cmd("testdata/one-and-done.sh")
run_cmd("testdata/daemonizer.sh")
print "============= ending test =============="
