import base64
import copy
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prototype_receive as receiver
from prototype_release import IDENTITY, PROFILE, configuration_digest, create, render, validate, verify


def release():
    data = {'version': 1, 'profile': PROFILE, 'backendSha': 'a' * 40, 'frontendSha': 'b' * 40,
            'deploySha': 'c' * 40, 'runId': '12345', 'runAttempt': '1', 'configurationSha256': 'd' * 64,
            'releaseId': 'prototype-' + 'a' * 40 + '-12345-1'}
    data['images'] = {name: {'repository': 'ghcr.io/cvn-mosprom/' + name, 'digest': 'sha256:' + 'e' * 64,
                            'sourceSha': data['backendSha'], 'frontendSha': data['frontendSha'], 'profile': PROFILE,
                            'runId': '12345', 'runAttempt': '1'} for name in ('api', 'bot', 'sim', 'web')}
    return data


@pytest.mark.parametrize('mutate', [
    lambda d: d['images'].pop('web'),
    lambda d: d['images'].update(patroni=copy.deepcopy(d['images']['api'])),
    lambda d: d['images']['api'].update(digest='latest'),
    lambda d: d['images']['bot'].update(repository='attacker.example/bot'),
    lambda d: d['images']['sim'].update(sourceSha='f' * 40),
    lambda d: d['images']['web'].update(runAttempt='2'),
    lambda d: d.update(profile='ha'),
    lambda d: d.update(releaseId='../../etc/passwd'),
])
def test_untrusted_or_mixed_release_rejected(mutate):
    data = release()
    mutate(data)
    with pytest.raises(ValueError):
        validate(data)


def test_only_application_images_are_rendered():
    text = render(release())
    assert 'API_IMAGE=ghcr.io/cvn-mosprom/api@sha256:' in text
    assert 'POSTGRES_IMAGE' not in text and 'REDIS_IMAGE' not in text


def test_failed_signature_prevents_all_delivery():
    with patch('prototype_release.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'cosign')) as runner:
        with pytest.raises(subprocess.CalledProcessError):
            verify(release())
    assert IDENTITY in runner.call_args.args[0]


def test_signature_with_wrong_profile_or_build_is_not_accepted():
    payload = {'predicate': {'buildDefinition': {'externalParameters': {'mospromSource': {'backendSha': 'a' * 40, 'frontendSha': 'b' * 40}}}}}
    raw = json.dumps({'payload': base64.b64encode(json.dumps(payload).encode()).decode()})
    with patch('prototype_release.subprocess.run'), patch('prototype_release.subprocess.check_output', return_value=raw):
        with pytest.raises(ValueError, match='provenance'):
            verify(release())


def test_valid_slsa_parameters_keep_the_complete_build_coordinates():
    data = release()
    coordinates = {name: data[name] for name in ('backendSha', 'frontendSha', 'profile', 'runId', 'runAttempt')}
    statement = {'predicate': {'buildDefinition': {'externalParameters': {'mospromSource': coordinates}}}}
    raw = json.dumps({'payload': base64.b64encode(json.dumps(statement).encode()).decode()})
    with patch('prototype_release.subprocess.run') as signatures, \
            patch('prototype_release.subprocess.check_output', return_value=raw):
        verify(data)
    assert signatures.call_count == 4


def test_configuration_drift_blocks_before_registry_or_docker(tmp_path):
    with patch.object(receiver, 'CONFIG', tmp_path), patch.object(receiver, 'configuration_digest', return_value='f' * 64), \
            patch.object(receiver, 'verify') as checked, patch.object(receiver, 'run') as command:
        with pytest.raises(ValueError, match='drift'):
            receiver.deploy(release(), 'synthetic-test-token-which-is-not-a-secret')
    checked.assert_not_called()
    command.assert_not_called()


def test_ephemeral_registry_auth_uses_the_actual_actions_actor(tmp_path):
    captured = {}
    data = release()

    def checked(_data, *, env):
        configuration = json.loads((Path(env['DOCKER_CONFIG']) / 'config.json').read_text())
        captured['credential'] = base64.b64decode(configuration['auths']['ghcr.io']['auth']).decode()
        raise RuntimeError('stop before any Docker changes')

    with patch.object(receiver, 'STATE', tmp_path), \
            patch.object(receiver, 'configuration_digest', return_value=data['configurationSha256']), \
            patch.object(receiver, 'verify', side_effect=checked):
        with pytest.raises(RuntimeError):
            receiver.deploy(data, 'synthetic-token', 'ci-actor')
    assert captured['credential'] == 'ci-actor:synthetic-token'
    assert not list(tmp_path.glob('registry-*'))


def test_opaque_jwt_registry_tokens_are_supported():
    assert receiver.valid_registry_token('header.' + 'a' * 1600 + '.signature-with-dashes')


@pytest.mark.parametrize('token', [None, '', 'a' * 8193, 'a' * 20 + '\n', 'a' * 20 + '\0', ' ' * 30])
def test_oversized_or_control_character_tokens_are_rejected(token):
    assert not receiver.valid_registry_token(token)


def test_operational_revision_gets_a_distinct_immutable_release_id(tmp_path):
    from prototype_release import CONFIG_FILES
    data = release()
    for name in CONFIG_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    for name, image in data['images'].items():
        directory = artifacts / name
        directory.mkdir()
        (directory / 'image.json').write_text(json.dumps({'name': name, **image}))
    first = create(artifacts, backend_sha=data['backendSha'], frontend_sha=data['frontendSha'], root=tmp_path, deploy_sha='c' * 40)
    second = create(artifacts, backend_sha=data['backendSha'], frontend_sha=data['frontendSha'], root=tmp_path, deploy_sha='d' * 40)
    assert first['images'] == second['images']
    assert first['releaseId'] != second['releaseId']


def test_stale_telegram_menu_is_reconciled_without_sending_messages(tmp_path):
    from unittest.mock import MagicMock
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('BOT_TOKEN=synthetic\nWEBAPP_URL=https://ochakovo.velikoss.ru/app\n')
    replies = [
        {'ok': True, 'result': {'username': 'cvnprombot'}},
        {'ok': True, 'result': {'type': 'web_app', 'web_app': {'url': 'https://old.example/app'}}},
        {'ok': True, 'result': True},
        {'ok': True, 'result': {'type': 'web_app', 'web_app': {'url': 'https://ochakovo.velikoss.ru/app'}}},
    ]
    opener = MagicMock()
    responses = []
    for data in replies:
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        responses.append(response)
    opener.open.side_effect = responses
    with patch.object(receiver, 'RUNTIME', runtime), patch.object(receiver.urllib.request, 'build_opener', return_value=opener):
        receiver.reconcile_telegram_menu()
    requests = [item.args[0] for item in opener.open.call_args_list]
    assert [item.full_url.rsplit('/', 1)[-1].split('?', 1)[0] for item in requests] == [
        'getMe', 'getChatMenuButton', 'setChatMenuButton', 'getChatMenuButton']
    from urllib.parse import parse_qs, urlsplit
    assert all(item.get_method() == 'POST' and not urlsplit(item.full_url).query for item in requests)
    assert json.loads(parse_qs(requests[2].data.decode())['menu_button'][0])['web_app']['url'] == 'https://ochakovo.velikoss.ru/app'


def test_compose_commands_have_one_fixed_project_and_configuration():
    command = receiver.dc(Path('/fixed/images.env'), 'up', '-d', '--no-deps', *receiver.SERVICES)
    assert command[:4] == ['docker', 'compose', '--project-name', 'mosprom-prototype']
    assert '--no-deps' in command
    assert 'patroni' not in command and 'etcd' not in command and 'db' not in receiver.SERVICES


def test_configuration_fingerprint_changes_with_caddy(tmp_path):
    from prototype_release import CONFIG_FILES
    for name in CONFIG_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    before = configuration_digest(tmp_path)
    (tmp_path / 'compose/prototype.Caddyfile').write_text('changed')
    assert configuration_digest(tmp_path) != before


def test_backup_failure_cannot_stop_bot_or_run_migrations(tmp_path):
    data = release()
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        if 'pg_dump' in command:
            raise subprocess.CalledProcessError(1, command)

    with patch.object(receiver, 'STATE', tmp_path), \
            patch.object(receiver, 'configuration_digest', return_value=data['configurationSha256']), \
            patch.object(receiver, 'verify'), patch.object(receiver, 'reconcile_telegram_menu'), patch.object(receiver, 'database_version', return_value='one'), \
            patch.object(receiver.subprocess, 'check_output', return_value='amd64'), patch.object(receiver, 'run', side_effect=invoke):
        with pytest.raises(subprocess.CalledProcessError):
            receiver.deploy(data, 'synthetic-test-token')
    assert any('pg_dump' in command for command in calls)
    assert not any('stop' in command or 'migrate' in command for command in calls)


@pytest.mark.parametrize('after,expected_rollbacks', [('one', 1), ('two', 0)])
def test_failed_migration_only_rolls_back_when_schema_did_not_change(tmp_path, after, expected_rollbacks):
    data = release()
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        if 'pg_dump' in command:
            kwargs['stdout'].write(b'x' * 1000)
        if 'migrate' in command:
            raise subprocess.CalledProcessError(1, command)

    with patch.object(receiver, 'STATE', tmp_path), \
            patch.object(receiver, 'configuration_digest', return_value=data['configurationSha256']), \
            patch.object(receiver, 'verify'), patch.object(receiver, 'reconcile_telegram_menu'), patch.object(receiver, 'database_version', side_effect=['one', after]), \
            patch.object(receiver.subprocess, 'check_output', return_value='amd64'), patch.object(receiver, 'run', side_effect=invoke):
        with pytest.raises(subprocess.CalledProcessError):
            receiver.deploy(data, 'synthetic-test-token')
    assert sum('up' in command for command in calls) == expected_rollbacks
    assert not (tmp_path / 'current.json').exists()
    assert not any('restore' in command for command in calls)


def test_external_menu_failure_is_rejected_before_any_docker_change(tmp_path):
    data = release()
    with patch.object(receiver, 'STATE', tmp_path), \
            patch.object(receiver, 'configuration_digest', return_value=data['configurationSha256']), \
            patch.object(receiver, 'verify'), \
            patch.object(receiver, 'reconcile_telegram_menu', side_effect=receiver.TelegramMenuError('bot_menu_stale')), \
            patch.object(receiver, 'run') as command:
        with pytest.raises(receiver.TelegramMenuError):
            receiver.deploy(data, 'synthetic-token', 'ci-actor')
    command.assert_not_called()
    assert not (tmp_path / 'releases').exists()


def test_true_telegram_acknowledgement_cannot_hide_an_unchanged_menu(tmp_path):
    from unittest.mock import MagicMock
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('BOT_TOKEN=synthetic\nWEBAPP_URL=https://ochakovo.velikoss.ru/app\n')
    stale = {'ok': True, 'result': {'type': 'web_app', 'web_app': {'url': 'https://old.example/app'}}}
    replies = [{'ok': True, 'result': {'username': 'cvnprombot'}}, stale,
               {'ok': True, 'result': True}, *[stale] * 4]
    opener = MagicMock()
    responses = []
    for data in replies:
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(data).encode())
        responses.append(response)
    opener.open.side_effect = responses
    with patch.object(receiver, 'RUNTIME', runtime), \
            patch.object(receiver.urllib.request, 'build_opener', return_value=opener), \
            patch.object(receiver.time, 'sleep') as delay:
        with pytest.raises(receiver.TelegramMenuError, match='bot_menu_stale'):
            receiver.reconcile_telegram_menu()
    assert opener.open.call_count == 7
    assert delay.call_count == 3
