import sys
import shutil
import filecmp
import tarfile
from tempfile import mkdtemp
import re
import os
import unittest
import inspect
import yaml

sys.path.append('../core')
from cloudcoreo_agent import *

# Enable DEBUG for verbose test output
DEBUG = False
# In general DEBUG_AGENT should be True to prevent scripts in the test_package from running
DEBUG_AGENT = True


class CompositeTests(unittest.TestCase):

    _tmpdir = mkdtemp()

    def setUp(self):
        tar = tarfile.open(("testdata/%s.tgz" % self._test_package))
        tar.extractall(self._tmpdir)
        tar.close()

        self._workdir = os.path.join(self._tmpdir, self._test_package.split("-")[0])
        self._repodir = os.path.join(self._workdir, "repo")
        self._agent_conf = os.path.join(self._tmpdir, "agent.conf")

        shutil.copy("testdata/agent.conf", self._agent_conf)

        with open(self._agent_conf, 'r') as ymlfile:
            configs = yaml.load(ymlfile)

        # Save agent_uuid to config file
        with open(self._agent_conf, 'w') as ymlfile:
            configs['work_dir'] = self._workdir
            configs['debug'] = DEBUG_AGENT
            ymlfile.write(yaml.dump(configs, default_style="'"))

    def tearDown(self):
        # cleanup
        shutil.rmtree(self._tmpdir)

    def file_dump(self, files):
        for filename in files:
            full_path_filename = os.path.join(self._repodir, filename)
            with open(full_path_filename, 'r') as openFile:
                content = openFile.read().replace('script-order:\n  - ', '').replace('\n', '')
                print "filename: %s : %s" % (filename, content)

    def compare_file_contents_to_str(self, files_hash, debug=DEBUG):
        compares = []
        for filename, value in files_hash.iteritems():
            full_path_filename = os.path.join(self._repodir, filename)
            with open(full_path_filename) as openFile:
                content = openFile.read().replace('script-order:\n  - ', '').replace('\n', '')
                compares.append(content == value)

                if debug:
                    print "filename: %s : %s : %s" % (filename, content, value)

        return compares

    def compare_file_contents(self, filesA, filesB, debug=DEBUG):
        if len(filesA) != len(filesB):
            return False
        compares = []
        indices = range(0, len(filesA))
        for index in indices:
            full_path_fileA = os.path.join(self._repodir, filesA[index])
            full_path_fileB = os.path.join(self._repodir, filesB[index])
            with open(full_path_fileA) as fileA:
                contentA = fileA.read().replace('script-order:\n  - ', '').replace('\n', '')
            with open(full_path_fileB) as fileB:
                contentB = fileB.read().replace('script-order:\n  - ', '').replace('\n', '')

            if debug:
                print "filesA[%d]: %s : %s" % (index, filesA[index], contentA)
                print "filesB[%d]: %s : %s" % (index, filesB[index], contentB)

            compares.append(contentA == contentB)

        return compares


class OverridesTests(CompositeTests):
    _truth_files_nat = [
        'stack-servers-nat/extends/boot-scripts/order.yaml',
    ]

    _truth_files_nat_overrides = [
        'overrides/stack-servers-nat/extends/boot-scripts/order.yaml'
    ]

    _truth_files_nat_overrides_content = {
        'stack-servers-nat/extends/boot-scripts/order.yaml': 'nb1o',
        'overrides/stack-servers-nat/extends/boot-scripts/order.yaml': 'nb1o'
    }

    _truth_files_vpn = [
        'stack-servers-vpn/extends/extends/boot-scripts/order.yaml',
        'stack-servers-vpn/extends/stack-servers-plus/boot-scripts/order.yaml',
        'stack-servers-vpn/extends/boot-scripts/order.yaml',
        'stack-servers-vpn/boot-scripts/order.yaml'
    ]

    _truth_files_vpn_overrides = [
        'stack-servers-vpn/extends/stack-servers-plus/overrides/boot-scripts/order.yaml',
        'stack-servers-vpn/extends/overrides/extends/boot-scripts/order.yaml',
        'stack-servers-vpn/extends/overrides/stack-servers-plus/boot-scripts/order.yaml',
        'stack-servers-vpn/extends/overrides/boot-scripts/order.yaml',
        'stack-servers-vpn/overrides/extends/overrides/extends/boot-scripts/order.yaml',
        'stack-servers-vpn/overrides/extends/overrides/stack-servers-plus/boot-scripts/order.yaml',
        'stack-servers-vpn/overrides/extends/overrides/boot-scripts/order.yaml',
        'stack-servers-vpn/overrides/extends/boot-scripts/order.yaml',
        'overrides/stack-servers-vpn/extends/overrides/extends/boot-scripts/order.yaml',
        'overrides/stack-servers-vpn/extends/boot-scripts/order.yaml'
    ]

    _truth_files_vpn_overrides_content = {
        'stack-servers-vpn/extends/extends/boot-scripts/order.yaml': 'vb1o',
        'stack-servers-vpn/extends/stack-servers-plus/boot-scripts/order.yaml': 'vb3oo',
        'stack-servers-vpn/extends/boot-scripts/order.yaml': 'vb2oooo',
        'stack-servers-vpn/boot-scripts/order.yaml': 'vb4',
        'stack-servers-vpn/extends/stack-servers-plus/overrides/boot-scripts/order.yaml': 'vb3o',
        'stack-servers-vpn/extends/overrides/extends/boot-scripts/order.yaml': 'vb1ooo',
        'stack-servers-vpn/extends/overrides/stack-servers-plus/boot-scripts/order.yaml': 'vb3ooo',
        'stack-servers-vpn/extends/overrides/boot-scripts/order.yaml': 'vb2oo',
        'stack-servers-vpn/overrides/extends/overrides/extends/boot-scripts/order.yaml': 'vb1oo',
        'stack-servers-vpn/overrides/extends/overrides/stack-servers-plus/boot-scripts/order.yaml': 'vb3ooo',
        'stack-servers-vpn/overrides/extends/overrides/boot-scripts/order.yaml': 'vb2oo',
        'stack-servers-vpn/overrides/extends/boot-scripts/order.yaml': 'vb2ooo',
        'overrides/stack-servers-vpn/extends/overrides/extends/boot-scripts/order.yaml': 'vb1ooo',
        'overrides/stack-servers-vpn/extends/boot-scripts/order.yaml': 'vb2oooo'
    }

    _truth_files_generic_before_override_dont_exist = [
        'extends/stack-vpc-private-only/README.md',
        'README.md',
        'root-file.txt',
        'stack-servers-nat/README.md',
        'stack-servers-nat/extends/boot-scripts/nb1o.sh',
        'stack-servers-nat/extra-files/data/data1.txt',
        'stack-servers-nat/extra-files/images/image1.txt',
        'stack-servers-vpn/README.md',
        'stack-servers-vpn/extends/overrides/boot-scripts/vb2oo.sh'
    ]
    _truth_files_generic_before_override_exist = [
        'stack-servers-nat/extends/README.md',
        'stack-servers-vpn/extends/README.md',
        'stack-servers-vpn/operational-scripts/order.yaml'
    ]

    _truth_files_generic_overrides = [
        'extends/stack-vpc-private-only/overrides/README.md',
        'overrides/README.md',
        'overrides/root-file.txt',
        'overrides/stack-servers-nat/extends/boot-scripts/nb1o.sh',
        'overrides/stack-servers-nat/extra-files/data/data1.txt',
        'overrides/stack-servers-nat/extra-files/images/image1.txt',
        'stack-servers-nat/extends/overrides/README.md',
        'stack-servers-nat/overrides/README.md',
        'stack-servers-vpn/extends/overrides/README.md',
        'stack-servers-vpn/overrides/extends/overrides/boot-scripts/vb2oo.sh',
        'stack-servers-vpn/overrides/operational-scripts/order.yaml',
        'stack-servers-vpn/overrides/README.md'
    ]

    _truth_files_generic_before_overrides_content = {
        'stack-servers-nat/extends/README.md': 'overridden1',
        'stack-servers-vpn/extends/README.md': 'overridden2',
        'stack-servers-vpn/operational-scripts/order.yaml': 'stack-servers-vpn/operational-scripts',
        'extends/stack-vpc-private-only/overrides/README.md': 'overrides1',
        'overrides/README.md': 'overrides2',
        'overrides/root-file.txt': 'moves to repo root',
        'overrides/stack-servers-nat/extends/boot-scripts/nb1o.sh': '#/bin/bashecho "nb1o"',
        'overrides/stack-servers-nat/extra-files/data/data1.txt': 'data1_text',
        'overrides/stack-servers-nat/extra-files/images/image1.txt': 'image1_text',
        'stack-servers-nat/extends/overrides/README.md': 'overrides3',
        'stack-servers-nat/overrides/README.md': 'overrides4',
        'stack-servers-vpn/extends/overrides/README.md': 'overrides5',
        'stack-servers-vpn/overrides/extends/overrides/boot-scripts/vb2oo.sh': '#/bin/bashecho "vb2oo"',
        'stack-servers-vpn/overrides/operational-scripts/order.yaml': 'stack-servers-vpn/overrides/operational-scripts',
        'stack-servers-vpn/overrides/README.md': 'overrides6'
    }

    _truth_files_generic_after_overrides_content = {
        'extends/stack-vpc-private-only/README.md': 'overrides1',
        'README.md': 'overrides2',
        'root-file.txt': 'moves to repo root',
        'stack-servers-nat/README.md': 'overrides4',
        'stack-servers-nat/extends/boot-scripts/nb1o.sh': '#/bin/bashecho "nb1o"',
        'stack-servers-nat/extra-files/data/data1.txt': 'data1_text',
        'stack-servers-nat/extra-files/images/image1.txt': 'image1_text',
        'stack-servers-vpn/README.md': 'overrides6',
        'stack-servers-vpn/extends/overrides/boot-scripts/vb2oo.sh': '#/bin/bashecho "vb2oo"',
        'stack-servers-nat/extends/README.md': 'overrides3',
        'stack-servers-vpn/extends/README.md': 'overrides5',
        'stack-servers-vpn/operational-scripts/order.yaml': 'stack-servers-vpn/overrides/operational-scripts'
    }

    _test_package = "57a1fa37c514992cf3958242-precedence-test-data-old-branch-model"

    def bootscripts_check(self, server, truth_files):
        override = False
        test_files = precedence_walk(self._repodir, "boot-scripts/order.yaml", server, override, DEBUG)

        if DEBUG:
            print "--------- truth_files [%d] ----------" % len(truth_files)
            print truth_files
            print "--------- test_files [%d] ----------" % len(test_files)
            print [re.sub('.*/repo/', '', entry) for entry in test_files]

        compare_files = self.compare_file_contents(truth_files, test_files)

        if DEBUG:
            print "file contents compare: %s" % compare_files

        self.assertEqual(len(truth_files), len(test_files), "before and after did not return same number of files!")
        [self.assertTrue(item, "unexpected file contents") for item in compare_files]

    def test_servers_nat_bootscripts(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        server = "servers-nat"
        self.bootscripts_check(server, self._truth_files_nat)

    def test_servers_vpn_bootscripts(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        server = "servers-vpn"
        self.bootscripts_check(server, self._truth_files_vpn)

    def overrides_check(self, lookfor, server, truth_files, truth_files_overrides, truth_files_content_hash):
        if DEBUG:
            print "========= before overrides =========="
            self.file_dump(truth_files + truth_files_overrides)

        override = True
        test_files = precedence_walk(self._repodir, lookfor, server, override, DEBUG)

        if DEBUG:
            print "--------- truth_files_overrides [%d] ----------" % len(truth_files_overrides)
            print self._truth_files_nat_overrides
            print "--------- test_files [%d] ----------" % len(test_files)
            print [re.sub('.*/repo/', '', entry) for entry in test_files]

            print "========= after overrides =========="
            self.file_dump(truth_files + [re.sub('.*/repo/', '', entry) for entry in test_files])

        compare_files = self.compare_file_contents_to_str(truth_files_content_hash)
        if DEBUG:
            print compare_files

        self.assertEqual(len(truth_files_overrides), len(test_files), "before and after did not return same number of files!")
        [self.assertTrue(item) for item in compare_files]

    def test_servers_nat_bootscripts_overrides(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        lookfor = "boot-scripts/order.yaml"
        server = "servers-nat"
        self.overrides_check(lookfor, server, self._truth_files_nat, self._truth_files_nat_overrides, self._truth_files_nat_overrides_content)

    def test_servers_vpn_bootscripts_overrides(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        lookfor = "boot-scripts/order.yaml"
        server = "servers-vpn"
        self.overrides_check(lookfor, server, self._truth_files_vpn, self._truth_files_vpn_overrides, self._truth_files_vpn_overrides_content)

    def test_general_overrides(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name

        before_overrides_compare_files = self.compare_file_contents_to_str(self._truth_files_generic_before_overrides_content)
        [self.assertTrue(item) for item in before_overrides_compare_files]
        if DEBUG:
            print before_overrides_compare_files

        truth_files = self._truth_files_nat_overrides + self._truth_files_vpn_overrides + self._truth_files_generic_overrides

        lookfor = ""
        server = ""
        override = True
        test_files = precedence_walk(self._repodir, lookfor, server, override, DEBUG)

        self.assertEqual(len(truth_files), len(test_files), "before and after did not return same number of files!")

        if DEBUG:
            print "--------- truth_files [%d] ----------" % len(truth_files)
            print sorted(truth_files)
            print "--------- test_files [%d] ----------" % len(test_files)
            print sorted([re.sub('.*/repo/', '', entry) for entry in test_files])

        after_overrides_compare_files = self.compare_file_contents_to_str(self._truth_files_generic_after_overrides_content)
        [self.assertTrue(item) for item in after_overrides_compare_files]
        if DEBUG:
            print after_overrides_compare_files


class OldAndNewCompareTests(CompositeTests):
    _test_package = "57a1fa37c514992cf3958242-precedence-test-data-old-branch-model"

    @unittest.expectedFailure
    def test_old_vs_new_bootscripts(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        get_order_files = get_script_order_files(self._tmpdir, "servers-nat")
        get_precedence_walk_files = precedence_walk(self._repodir, "boot-scripts/order.yaml", "servers-nat")

        print "--------- get_order_files [%d] ----------" % len(get_order_files)
        print [re.sub('.*/repo/', '', entry) for entry in get_order_files]
        print "--------- get_precedence_walk_files [%d] ----------"  % len(get_precedence_walk_files)
        print [re.sub('.*/repo/', '', entry) for entry in get_precedence_walk_files]

        self.assertEqual(len(get_order_files), len(get_precedence_walk_files), "before and after did not return same number of files!")


class RunBootScripts(CompositeTests):

    _test_package = "57a1fa37c514992cf3958242-precedence-test-data-old-branch-model"

    def test_run_all_boot_scripts(self):
        print "<<<<< Running test:  %s  >>>>>" % inspect.currentframe().f_code.co_name
        load_configs(self._agent_conf)

        server_name = "servers-nat"
        num_expected = 1
        num_nat_order_files = run_all_boot_scripts(self._repodir, server_name)
        print "---> ran %d order.yaml files for %s" % (num_nat_order_files, server_name)
        self.assertEqual(num_nat_order_files, num_expected, "expected to run %d script for %s" % (num_expected, server_name))

        server_name = "servers-vpn"
        num_expected = 4
        num_vpn_order_files = run_all_boot_scripts(self._repodir, server_name)
        print "---> ran %d order.yaml files for %s" % (num_vpn_order_files, server_name)
        self.assertEqual(num_vpn_order_files, num_expected, "expected to run %d script for %s" % (num_expected, server_name))


def suite():
    test_suite = unittest.TestSuite()

    overrides_tests = [
        'test_servers_nat_bootscripts',
        'test_servers_vpn_bootscripts',
        'test_servers_nat_bootscripts_overrides',
        'test_servers_vpn_bootscripts_overrides',
        'test_general_overrides'
    ]
    test_suite.addTests(map(OverridesTests, overrides_tests))

    compare_tests = ['test_old_vs_new_bootscripts']
    test_suite.addTests(map(OldAndNewCompareTests, compare_tests))

    run_script_tests = ['run_all_bootscripts']
    test_suite.addTests(map(RunBootScripts, run_script_tests))

    return test_suite


if __name__ == '__main__':
    unittest.main()
