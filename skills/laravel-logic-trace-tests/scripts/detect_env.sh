#!/usr/bin/env bash
# Phase 0: detect the Laravel project environment. Run from the project root.
# Writes .trace/env.txt and prints it. Prints "STOP:" lines for blockers.
set -u
mkdir -p .trace
out=.trace/env.txt
: > "$out"
say() { echo "$*" | tee -a "$out"; }

if [ ! -f artisan ]; then
  say "STOP: no 'artisan' file here. Run from the Laravel project root."
  exit 1
fi

say "laravel: $(php artisan --version 2>/dev/null || echo 'unknown (php not runnable)')"
say "php: $(php -r 'echo PHP_VERSION;' 2>/dev/null || echo unknown)"

if [ -f vendor/bin/pest ] || grep -q '"pestphp/pest"' composer.json 2>/dev/null; then
  say "runner: pest"
  say "test_command: php artisan test   (or vendor/bin/pest)"
else
  say "runner: phpunit"
  say "test_command: php artisan test   (or vendor/bin/phpunit)"
fi

cfg=""
[ -f phpunit.xml ] && cfg=phpunit.xml
[ -z "$cfg" ] && [ -f phpunit.xml.dist ] && cfg=phpunit.xml.dist
if [ -n "$cfg" ]; then
  conn=$(grep -E 'name="DB_CONNECTION"' "$cfg" | head -1 | sed -E 's/.*value="([^"]*)".*/\1/')
  dbname=$(grep -E 'name="DB_DATABASE"' "$cfg" | head -1 | sed -E 's/.*value="([^"]*)".*/\1/')
  say "test_db_connection: ${conn:-NOT SET in $cfg}"
  say "test_db_database: ${dbname:-NOT SET in $cfg}"
  if [ -z "${conn:-}" ]; then
    if [ -f .env.testing ]; then
      say "note: DB not set in $cfg; .env.testing exists, check it before probing"
    else
      say "STOP: $cfg does not set DB_CONNECTION and there is no .env.testing. Probes could hit the default database. Ask the user to configure a test DB."
    fi
  elif [ "$conn" != "sqlite" ] && [ -z "${dbname:-}" ] && [ ! -f .env.testing ]; then
    say "STOP: non-sqlite test connection without a DB_DATABASE override. Ask the user which test database to use."
  fi
else
  say "STOP: no phpunit.xml found. Ask the user how tests are configured."
fi

if grep -rqE "RefreshDatabase|DatabaseTransactions|LazilyRefreshDatabase" tests 2>/dev/null; then
  trait=$(grep -rhoE "RefreshDatabase|DatabaseTransactions|LazilyRefreshDatabase" tests | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
  say "db_trait_in_use: $trait"
else
  say "db_trait_in_use: none found (check Pest.php uses(...) or the base TestCase)"
fi

say "feature_tests: $(find tests/Feature -name '*Test.php' 2>/dev/null | wc -l | tr -d ' ')"
say "unit_tests: $(find tests/Unit -name '*Test.php' 2>/dev/null | wc -l | tr -d ' ')"
