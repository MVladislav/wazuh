# Copyright (C) 2015, Wazuh Inc.
# Created by Wazuh, Inc. <info@wazuh.com>.
# This program is free software; you can redistribute it and/or modify it under the terms of GPLv2

import asyncio
import signal
import sys
from unittest.mock import call, patch, Mock

import pytest

import scripts.wazuh_clusterd as wazuh_clusterd
from wazuh.core import pyDaemonModule
from wazuh.core.cluster.utils import HAPROXY_DISABLED, HAPROXY_HELPER

wazuh_clusterd.pyDaemonModule = pyDaemonModule


def test_set_logging():
    """Check and set the behavior of set_logging function."""
    import wazuh.core.cluster.utils as cluster_utils

    wazuh_clusterd.cluster_utils = cluster_utils
    with patch.object(cluster_utils, 'ClusterLogger') as clusterlogger_mock:
        assert wazuh_clusterd.set_logging(foreground_mode=False, debug_mode=0)
        clusterlogger_mock.assert_called_once_with(
            foreground_mode=False, log_path='logs/cluster.log', debug_level=0,
            tag='%(asctime)s %(levelname)s: [%(tag)s] [%(subtag)s] %(message)s')


@patch('builtins.print')
def test_print_version(print_mock):
    """Set the scheme to be printed."""
    with patch('wazuh.core.cluster.__version__', 'TEST'):
        wazuh_clusterd.print_version()
        print_mock.assert_called_once_with(
            '\nWazuh TEST - Wazuh Inc\n\nThis program is free software; you can redistribute it and/or modify\n'
            'it under the terms of the GNU General Public License (version 2) as \npublished by the '
            'Free Software Foundation. For more details, go to \nhttps://www.gnu.org/licenses/gpl.html\n')


@patch('scripts.wazuh_clusterd.os.getpid', return_value=1001)
def test_exit_handler(os_getpid_mock):
    """Set the behavior when exiting the script."""

    class SignalMock:
        SIGTERM = 0
        SIG_DFL = 1

        class Signals:
            def __init__(self, signum):
                self.name = signum

        @staticmethod
        def signal(signalnum, handler):
            assert signalnum == 9
            assert handler == SignalMock.SIG_DFL

    class LoggerMock:
        def __init__(self):
            pass

        def info(self, msg):
            pass

    def original_sig_handler(signum, frame):
        pass

    original_sig_handler_not_callable = 1

    wazuh_clusterd.main_logger = LoggerMock()
    wazuh_clusterd.original_sig_handler = original_sig_handler
    with patch('scripts.wazuh_clusterd.signal', SignalMock), \
        patch.object(wazuh_clusterd, 'main_logger') as main_logger_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'delete_child_pids') as delete_child_pids_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'delete_pid') as delete_pid_mock, \
        patch.object(wazuh_clusterd, 'original_sig_handler') as original_sig_handler_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'get_parent_pid', return_value=999), \
        patch('scripts.wazuh_clusterd.os.kill') as os_kill_mock:
        wazuh_clusterd.exit_handler(9, 99)
        main_logger_mock.assert_has_calls([call.info('SIGNAL [(9)-(9)] received. Shutting down...')])
        os_kill_mock.assert_has_calls([
            call(999, SignalMock.SIGTERM),
            call(999, SignalMock.SIGTERM),
        ])
        delete_child_pids_mock.assert_has_calls([
            call('wazuh-clusterd', os_getpid_mock.return_value, main_logger_mock),
        ])
        delete_pid_mock.assert_has_calls([
            call('wazuh-clusterd', os_getpid_mock.return_value),
        ])
        original_sig_handler_mock.assert_called_once_with(9, 99)
        main_logger_mock.reset_mock()
        delete_child_pids_mock.reset_mock()
        delete_pid_mock.reset_mock()
        original_sig_handler_mock.reset_mock()

        wazuh_clusterd.original_sig_handler = original_sig_handler_not_callable
        wazuh_clusterd.exit_handler(9, 99)
        main_logger_mock.assert_has_calls([call.info('SIGNAL [(9)-(9)] received. Shutting down...')])
        os_kill_mock.assert_has_calls([
            call(999, SignalMock.SIGTERM),
            call(999, SignalMock.SIGTERM),
        ])
        delete_child_pids_mock.assert_has_calls([
            call('wazuh-clusterd', 1001, main_logger_mock),
        ])
        delete_pid_mock.assert_has_calls([
            call('wazuh-clusterd', 1001),
        ])
        original_sig_handler_mock.assert_not_called()


@pytest.mark.parametrize("foreground, root", [
    (True, True),
    (True, False),
    (False, True),
    (False, False),
])
@patch('subprocess.Popen')
def test_start_daemons(mock_popen, foreground, root):
    """Validate that `start_daemons` works as expected."""
    from wazuh.core import pyDaemonModule

    class LoggerMock:
        def __init__(self):
            pass

        def info(self, msg):
            pass

    wazuh_clusterd.main_logger = LoggerMock
    pid = 2
    process_mock = Mock()
    attrs = {'poll.return_value': 0, 'wait.return_value': 0}
    process_mock.configure_mock(**attrs)
    mock_popen.return_value = process_mock
    

    with patch.object(wazuh_clusterd, 'main_logger') as main_logger_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'get_parent_pid', return_value=pid), \
        patch.object(wazuh_clusterd.pyDaemonModule, 'create_pid'):
        wazuh_clusterd.start_daemons(foreground, root)

    mock_popen.assert_has_calls([
        call([wazuh_clusterd.ENGINE_BINARY_PATH, 'server', 'start']),
        call([wazuh_clusterd.EMBEDDED_PYTHON_PATH, wazuh_clusterd.MANAGEMENT_API_SCRIPT_PATH] + \
              (['-r'] if root else []) + (['-f'] if foreground else [])),
        call([wazuh_clusterd.EMBEDDED_PYTHON_PATH, wazuh_clusterd.COMMS_API_SCRIPT_PATH] + \
              (['-r'] if root else []) + (['-f'] if foreground else [])),
    ], any_order=True)

    if foreground:
        pid = mock_popen().pid

    main_logger_mock.info.assert_has_calls([
        call(f'Started wazuh-engined (pid: {mock_popen().pid})'),
        call(f'Started wazuh-apid (pid: {pid})'),
        call(f'Started wazuh-comms-apid (pid: {pid})'),
    ])


@patch('subprocess.Popen')
def test_start_daemons_ko(mock_popen):
    """Validate that `start_daemons` works as expected when the subprocesses fail."""
    class LoggerMock:
        def __init__(self):
            pass

        def info(self, msg):
            pass

    wazuh_clusterd.main_logger = LoggerMock
    pid = 2
    process_mock = Mock()
    attrs = {'poll.return_value': 1, 'wait.return_value': 1}
    process_mock.configure_mock(**attrs)
    mock_popen.return_value = process_mock

    with patch.object(wazuh_clusterd, 'main_logger') as main_logger_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'get_parent_pid', return_value=pid):
        wazuh_clusterd.start_daemons(False, False)

    mock_popen.assert_has_calls([
        call([wazuh_clusterd.ENGINE_BINARY_PATH, 'server', 'start']),
        call([wazuh_clusterd.EMBEDDED_PYTHON_PATH, wazuh_clusterd.MANAGEMENT_API_SCRIPT_PATH]),
        call([wazuh_clusterd.EMBEDDED_PYTHON_PATH, wazuh_clusterd.COMMS_API_SCRIPT_PATH]),
    ], any_order=True)

    main_logger_mock.error.assert_has_calls([
        call('Error starting wazuh-engined: return code 1'),
        call('Error starting wazuh-apid: return code 1'),
        call('Error starting wazuh-comms-apid: return code 1'),
    ])


@patch('scripts.wazuh_clusterd.os.kill')
@patch('scripts.wazuh_clusterd.os.getpid', return_value=999)
def test_shutdown_daemon(os_getpid_mock, os_kill_mock):
    """Validate that `shutdown_daemon` works as expected."""
    class LoggerMock:
        def __init__(self):
            pass

        def info(self, msg):
            pass

    wazuh_clusterd.main_logger = LoggerMock

    with patch.object(wazuh_clusterd, 'main_logger') as main_logger_mock, \
        patch.object(wazuh_clusterd.pyDaemonModule, 'get_parent_pid', return_value=os_getpid_mock.return_value):
        wazuh_clusterd.shutdown_daemon(wazuh_clusterd.MANAGEMENT_API_DAEMON_NAME)

    os_kill_mock.assert_called_once_with(999, signal.SIGTERM)
    main_logger_mock.info.assert_has_calls([
        call(f'Shutting down {wazuh_clusterd.MANAGEMENT_API_DAEMON_NAME} (pid: {os_getpid_mock.return_value})'),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize('helper_disabled', (True, False))
async def test_master_main(helper_disabled: bool):
    """Check and set the behavior of master_main function."""
    import wazuh.core.cluster.utils as cluster_utils
    cluster_config = {'test': 'config', HAPROXY_HELPER: {HAPROXY_DISABLED: helper_disabled}}

    class Arguments:
        def __init__(self, performance_test, concurrency_test):
            self.performance_test = performance_test
            self.concurrency_test = concurrency_test

    class TaskPoolMock:
        def __init__(self):
            self._max_workers = 1

        def map(self, first, second):
            assert first == cluster_utils.process_spawn_sleep
            assert second == range(1)

    class MasterMock:
        def __init__(self, performance_test, concurrency_test, configuration, logger, cluster_items):
            assert performance_test == 'test_performance'
            assert concurrency_test == 'concurrency_test'
            assert configuration == cluster_config
            assert logger == 'test_logger'
            assert cluster_items == {'node': 'item'}
            self.task_pool = TaskPoolMock()

        def start(self):
            return 'MASTER_START'

    class LocalServerMasterMock:
        def __init__(self, performance_test, logger, concurrency_test, node, configuration, cluster_items):
            assert performance_test == 'test_performance'
            assert logger == 'test_logger'
            assert concurrency_test == 'concurrency_test'
            assert configuration == cluster_config
            assert cluster_items == {'node': 'item'}

        def start(self):
            return 'LOCALSERVER_START'

    class HAPHElperMock:
        @classmethod
        def start(cls):
            return 'HAPHELPER_START'


    async def gather(first, second, third=None):
        assert first == 'MASTER_START'
        assert second == 'LOCALSERVER_START'
        if third is not None:
            assert third == 'HAPHELPER_START'


    wazuh_clusterd.cluster_utils = cluster_utils
    args = Arguments(performance_test='test_performance', concurrency_test='concurrency_test')
    with patch('scripts.wazuh_clusterd.asyncio.gather', gather), \
        patch('wazuh.core.cluster.master.Master', MasterMock), \
        patch('wazuh.core.cluster.local_server.LocalServerMaster', LocalServerMasterMock), \
        patch('wazuh.core.cluster.hap_helper.hap_helper.HAPHelper', HAPHElperMock):
        await wazuh_clusterd.master_main(
            args=args,
            cluster_config=cluster_config,
            cluster_items={'node': 'item'},
            logger='test_logger'
        )

@pytest.mark.asyncio
@patch("asyncio.sleep", side_effect=IndexError)
async def test_worker_main(asyncio_sleep_mock):
    """Check and set the behavior of worker_main function."""
    import wazuh.core.cluster.utils as cluster_utils

    class Arguments:
        def __init__(self, performance_test, concurrency_test, send_file, send_string):
            self.performance_test = performance_test
            self.concurrency_test = concurrency_test
            self.send_file = send_file
            self.send_string = send_string

    class TaskPoolMock:
        def __init__(self):
            self._max_workers = 1

        def map(self, first, second):
            assert first == cluster_utils.process_spawn_sleep
            assert second == range(1)

    class LoggerMock:
        def __init__(self):
            pass

        def warning(self, msg):
            pass

    class WorkerMock:
        def __init__(self, performance_test, concurrency_test, configuration, logger, cluster_items, file, string,
                     task_pool):
            assert performance_test == 'test_performance'
            assert concurrency_test == 'concurrency_test'
            assert configuration == {'test': 'config'}
            assert file is True
            assert string is True
            assert logger == 'test_logger'
            assert cluster_items == {'intervals': {'worker': {'connection_retry': 34}}}
            assert task_pool is None
            self.task_pool = TaskPoolMock()

        def start(self):
            return 'WORKER_START'

    class LocalServerWorkerMock:
        def __init__(self, performance_test, logger, concurrency_test, node, configuration, cluster_items):
            assert performance_test == 'test_performance'
            assert logger == 'test_logger'
            assert concurrency_test == 'concurrency_test'
            assert configuration == {'test': 'config'}
            assert cluster_items == {'intervals': {'worker': {'connection_retry': 34}}}

        def start(self):
            return 'LOCALSERVER_START'

    async def gather(first, second):
        assert first == 'WORKER_START'
        assert second == 'LOCALSERVER_START'
        raise asyncio.CancelledError()

    wazuh_clusterd.cluster_utils = cluster_utils
    wazuh_clusterd.main_logger = LoggerMock
    args = Arguments(performance_test='test_performance', concurrency_test='concurrency_test',
                     send_file=True, send_string=True)

    with patch.object(wazuh_clusterd, 'main_logger') as main_logger_mock:
        with patch('concurrent.futures.ProcessPoolExecutor', side_effect=FileNotFoundError) as processpoolexecutor_mock:
            with patch('scripts.wazuh_clusterd.asyncio.gather', gather):
                with patch('scripts.wazuh_clusterd.logging.info') as logging_info_mock:
                    with patch('wazuh.core.cluster.worker.Worker', WorkerMock):
                        with patch('wazuh.core.cluster.local_server.LocalServerWorker', LocalServerWorkerMock):
                            with pytest.raises(IndexError):
                                await wazuh_clusterd.worker_main(
                                    args=args, cluster_config={'test': 'config'},
                                    cluster_items={'intervals': {'worker': {'connection_retry': 34}}},
                                    logger='test_logger')
                            processpoolexecutor_mock.assert_called_once_with(max_workers=1)
                            main_logger_mock.assert_has_calls([
                                call.warning(
                                    "In order to take advantage of Wazuh 4.3.0 cluster improvements, the directory "
                                    "'/dev/shm' must be accessible by the 'wazuh' user. Check that this file has "
                                    "permissions to be accessed by all users. Changing the file permissions to 777 "
                                    "will solve this issue."),
                                call.warning(
                                    'The Wazuh cluster will be run without the improvements added in Wazuh 4.3.0 and '
                                    'higher versions.')
                            ])
                            logging_info_mock.assert_called_once_with('Connection with server has been lost. '
                                                                      'Reconnecting in 10 seconds.')
                            asyncio_sleep_mock.assert_called_once_with(34)


@patch('scripts.wazuh_clusterd.argparse.ArgumentParser')
def test_get_script_arguments(argument_parser_mock):
    """Set the wazuh_clusterd script parameters."""
    from wazuh.core import common

    wazuh_clusterd.common = common
    with patch.object(wazuh_clusterd.common, 'OSSEC_CONF', 'testing/path'):
        wazuh_clusterd.get_script_arguments()
        argument_parser_mock.assert_called_once_with()
        argument_parser_mock.return_value.add_argument.assert_has_calls(
            [call('--performance_test', type=int, dest='performance_test', help='==SUPPRESS=='),
             call('--concurrency_test', type=int, dest='concurrency_test', help='==SUPPRESS=='),
             call('--string', help='==SUPPRESS==', type=int, dest='send_string'),
             call('--file', help='==SUPPRESS==', type=str, dest='send_file'),
             call('-f', help='Run in foreground', action='store_true', dest='foreground'),
             call('-d', help='Enable debug messages. Use twice to increase verbosity.', action='count',
                  dest='debug_level'),
             call('-V', help='Print version', action='store_true', dest='version'),
             call('-r', help='Run as root', action='store_true', dest='root'),
             call('-t', help='Test configuration', action='store_true', dest='test_config')]
        )


@patch('scripts.wazuh_clusterd.sys.exit', side_effect=sys.exit)
@patch('scripts.wazuh_clusterd.os.getpid', return_value=543)
@patch('scripts.wazuh_clusterd.os.setgid')
@patch('scripts.wazuh_clusterd.os.setuid')
@patch('scripts.wazuh_clusterd.os.chmod')
@patch('scripts.wazuh_clusterd.os.chown')
@patch('scripts.wazuh_clusterd.os.path.exists', return_value=True)
@patch('builtins.print')
def test_main(print_mock, path_exists_mock, chown_mock, chmod_mock, setuid_mock, setgid_mock, getpid_mock, exit_mock):
    """Check and set the behavior of wazuh_clusterd main function."""
    import wazuh.core.cluster.utils as cluster_utils
    from wazuh.core import common, pyDaemonModule

    class Arguments:
        def __init__(self, config_file, test_config, foreground, root):
            self.config_file = config_file
            self.test_config = test_config
            self.foreground = foreground
            self.root = root

    class LoggerMock:
        def __init__(self):
            pass

        def info(self, msg):
            pass

        def error(self, msg):
            pass

    args = Arguments(config_file='test', test_config=True, foreground=False, root=False)
    wazuh_clusterd.main_logger = LoggerMock()
    wazuh_clusterd.args = args
    wazuh_clusterd.common = common
    wazuh_clusterd.cluster_utils = cluster_utils
    with patch.object(common, 'wazuh_uid', return_value='uid_test'), \
        patch.object(common, 'wazuh_gid', return_value='gid_test'), \
        patch.object(wazuh_clusterd.cluster_utils, 'read_config', return_value={'node_type': 'master'}), \
        patch.object(wazuh_clusterd.main_logger, 'error') as main_logger_mock, \
        patch.object(wazuh_clusterd.main_logger, 'info') as main_logger_info_mock:
    
        with patch.object(wazuh_clusterd.cluster_utils, 'read_config', side_effect=Exception):
            with pytest.raises(SystemExit):
                wazuh_clusterd.main()
            main_logger_mock.assert_called_once()
            main_logger_mock.reset_mock()
            path_exists_mock.assert_any_call(f'{common.WAZUH_PATH}/logs/cluster.log')
            chown_mock.assert_called_with(f'{common.WAZUH_PATH}/logs/cluster.log', 'uid_test',
                                        'gid_test')
            chmod_mock.assert_called_with(f'{common.WAZUH_PATH}/logs/cluster.log', 432)
            exit_mock.assert_called_once_with(1)
            exit_mock.reset_mock()

        with patch('wazuh.core.cluster.cluster.check_cluster_config', side_effect=IndexError):
            with pytest.raises(SystemExit):
                wazuh_clusterd.main()
            main_logger_mock.assert_called_once()
            exit_mock.assert_called_once_with(1)
            exit_mock.reset_mock()

        with patch('wazuh.core.cluster.cluster.check_cluster_config', return_value=None):
            with pytest.raises(SystemExit):
                wazuh_clusterd.main()
            main_logger_mock.assert_called_once()
            exit_mock.assert_called_once_with(0)
            main_logger_mock.reset_mock()
            exit_mock.reset_mock()

            args.test_config = False
            wazuh_clusterd.args = args
            with patch('wazuh.core.cluster.cluster.clean_up') as clean_up_mock, \
                patch('scripts.wazuh_clusterd.clean_pid_files') as clean_pid_files_mock, \
                patch('wazuh.core.authentication.keypair_exists', return_value=False), \
                patch('wazuh.core.authentication.generate_keypair') as generate_keypair_mock, \
                patch('scripts.wazuh_clusterd.start_daemons') as start_daemons_mock, \
                patch.object(wazuh_clusterd.pyDaemonModule, 'get_parent_pid', return_value=999), \
                patch('os.kill') as os_kill_mock, \
                patch.object(wazuh_clusterd.pyDaemonModule, 'pyDaemon') as pyDaemon_mock, \
                patch.object(wazuh_clusterd.pyDaemonModule, 'create_pid') as create_pid_mock, \
                patch.object(wazuh_clusterd.pyDaemonModule, 'delete_child_pids'), \
                patch.object(wazuh_clusterd.pyDaemonModule,'delete_pid') as delete_pid_mock:
                wazuh_clusterd.main()
                main_logger_mock.assert_any_call(
                    "Unhandled exception: name 'cluster_items' is not defined")
                main_logger_mock.reset_mock()
                clean_up_mock.assert_called_once()
                clean_pid_files_mock.assert_called_once_with('wazuh-clusterd')
                pyDaemon_mock.assert_called_once()
                setuid_mock.assert_called_once_with('uid_test')
                setgid_mock.assert_called_once_with('gid_test')
                getpid_mock.assert_called()
                os_kill_mock.assert_has_calls([
                    call(999, signal.SIGTERM),
                    call(999, signal.SIGTERM),
                ])
                create_pid_mock.assert_called_once_with('wazuh-clusterd', 543)
                delete_pid_mock.assert_has_calls([
                    call('wazuh-clusterd', 543),
                ])
                main_logger_info_mock.assert_has_calls([
                    call('Generating JWT signing key pair'),
                    call('Shutting down wazuh-engined (pid: 999)'),
                    call('Shutting down wazuh-apid (pid: 999)'),
                    call('Shutting down wazuh-comms-apid (pid: 999)'),
                ])
                generate_keypair_mock.assert_called_once()
                start_daemons_mock.assert_called_once()

                args.foreground = True
                wazuh_clusterd.main()
                print_mock.assert_called_once_with('Starting cluster in foreground (pid: 543)')

                wazuh_clusterd.cluster_items = {}
                with patch('scripts.wazuh_clusterd.master_main', side_effect=KeyboardInterrupt('TESTING')):
                    wazuh_clusterd.main()
                    main_logger_info_mock.assert_any_call('SIGINT received. Shutting down...')

                with patch('scripts.wazuh_clusterd.master_main', side_effect=MemoryError('TESTING')):
                    wazuh_clusterd.main()
                    main_logger_mock.assert_any_call(
                        "Directory '/tmp' needs read, write & execution "
                        "permission for 'wazuh' user")
