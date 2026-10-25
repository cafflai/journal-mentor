param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$journalRoot = $PSScriptRoot
$codexCommand = Get-Command codex -ErrorAction Stop
$codexArgs = @(
    '-C', $journalRoot,
    '-c', 'features.memories=false',
    '-c', 'features.external_agent_memory_import=false',
    '-c', 'memories.generate_memories=false',
    '-c', 'memories.use_memories=false'
)
if ($CheckOnly) {
    & $codexCommand @codexArgs features list | Select-String -Pattern '^memories\s','^external_agent_memory_import\s'
    if ($LASTEXITCODE -ne 0) { throw 'Codex configuration check failed.' }
    Write-Output 'Only configuration flags were checked; no diary was read and no chat was started.'
    exit 0
}
# Start a NEW session. Do not resume a session that may already contain global memories.
$prompt = 'Use $journal-mentor to review recent diary entries. This new session was launched by start-mentor.ps1 with features.memories=false, features.external_agent_memory_import=false, memories.generate_memories=false and memories.use_memories=false. Keep all personal memory in this project. Read the skill and check the diary folder; do not search parent folders for entries. Reply in Chinese.'
& $codexCommand @codexArgs $prompt
exit $LASTEXITCODE
