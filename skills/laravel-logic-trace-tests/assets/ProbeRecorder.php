<?php

namespace Tests\Support;

/**
 * Writes what a probe observed to .trace/probes/<id>.json.
 * Throwaway helper: adjust the namespace to match composer.json autoload-dev.
 */
final class ProbeRecorder
{
    public static function save(string $probeId, string $decisionRow, array $observed, string $note = ''): void
    {
        $dir = base_path('.trace/probes');
        if (! is_dir($dir)) {
            mkdir($dir, 0775, true);
        }

        file_put_contents(
            $dir.'/'.$probeId.'.json',
            json_encode([
                'probe' => $probeId,
                'decision_row' => $decisionRow,
                'note' => $note,
                'observed' => $observed,
            ], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
        );
    }
}
