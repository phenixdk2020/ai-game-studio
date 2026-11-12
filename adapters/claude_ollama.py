"""Claude Code file tools with a local Ollama server; Studio owns test execution."""
import json
import urllib.request
import uuid


def settings(config):
    value = config.get('claude_ollama', {})
    url = str(value.get('base_url', 'http://127.0.0.1:11434')).rstrip('/')
    model = value.get('model', '')
    if url not in {'http://127.0.0.1:11434', 'http://localhost:11434'}:
        raise ValueError('Claude Ollama requires a loopback Ollama URL')
    if not isinstance(model, str) or not model.strip() or ':cloud' in model.lower():
        raise ValueError('Configure a local claude_ollama.model')
    return {'base_url': url, 'model': model}


def probe(config):
    selected = settings(config)
    request = urllib.request.Request(selected['base_url'] + '/api/show',
        data=json.dumps({'model': selected['model']}).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        model = json.load(response)
    if model.get('remote_model') or model.get('remote_host'):
        raise ValueError('Cloud models are not permitted for claude-ollama')
    if 'tools' not in model.get('capabilities', []):
        raise ValueError('Selected Ollama model must support tools')
    return selected


def execute(bridge, checkout, receipt, branch):
    selected = probe(bridge.config)  # Failure before dispatch is safe to correct.
    executable = bridge.tool('claude')
    help_result = bridge.command([executable, '--help'], 'claude-help', checkout)
    if '--restricted' not in help_result.stdout:
        raise ValueError('Update Claude Code: this integration requires --restricted')
    environment = {
        'ANTHROPIC_BASE_URL': selected['base_url'], 'ANTHROPIC_AUTH_TOKEN': 'ollama',
        'ANTHROPIC_API_KEY': '', 'CLAUDE_CONFIG_DIR': str(bridge.path/'claude-config'),
        'CLAUDE_CODE_USE_BEDROCK': '0', 'CLAUDE_CODE_USE_VERTEX': '0',
        'CLAUDE_CODE_USE_FOUNDRY': '0', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
        'CLAUDE_CODE_DISABLE_AUTO_MEMORY': '1', 'DISABLE_AUTOUPDATER': '1',
    }
    settings_path = bridge.path/'claude-settings.json'
    settings_path.write_text(json.dumps({'env': environment, 'disableAllHooks': True}), encoding='utf-8')
    mcp_path = bridge.path/'claude-mcp.json'
    mcp_path.write_text('{"mcpServers":{}}', encoding='utf-8')
    session = str(uuid.uuid4())
    receipt.update(branch=branch, stage='claude-ollama', status='Running',
                   sessionId=session, model=selected['model'], endpoint=selected['base_url'])
    bridge.save(receipt)  # Persist intent before starting; interrupted runs never redispatch.
    tools = 'Read,Edit,Write,Glob,Grep'
    instructions = bridge.prompt().replace('supplied with -C', 'supplied as the process working directory')
    instructions += ('\nUse your file tools to implement the requested changes in this working directory. '
                     'You have no shell tools. Do not edit .git or agent/tool configuration. '
                     'Studio runs the configured tests after you finish. Do not claim you ran tests.\n')
    result = bridge.command([executable, '-p', '--model', selected['model'],
        '--restricted', '--tools', tools, '--allowedTools', tools,
        '--permission-mode', 'acceptEdits', '--permission-prompts', 'none',
        '--setting-sources', '', '--settings', str(settings_path),
        '--strict-mcp-config', '--mcp-config', str(mcp_path),
        '--session-id', session, '--output-format', 'json'],
        'claude', checkout, extra_env=environment, input_text=instructions)
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError('Claude Code returned invalid JSON; inspect the existing session') from error
    if not isinstance(response, dict) or response.get('is_error') or response.get('subtype') != 'success':
        raise ValueError('Claude Code did not finish successfully; inspect bridge/claude.stdout.txt')
    if response.get('permission_denials'):
        raise ValueError('Claude Code reported denied tools; review the session before revalidating')
    (bridge.path/'claude-result.md').write_text(str(response.get('result', '')), encoding='utf-8')
    bridge.save(receipt)
