# slakwik-sermons-subs

Автоматическая транскрипция русскоязычных проповедей с RuTube.

Архитектура: **GitHub Actions** (cron-триггер раз в неделю + ручной запуск) → **Kaggle GPU** (`faster-whisper large-v3` через Kaggle API) → коммит транскриптов обратно в репо.

## Как добавить новый ролик

1. Открой [`videos.yml`](videos.yml).
2. Добавь запись в конец списка `videos:`:
   ```yaml
     - url: https://rutube.ru/video/<id>/
       title: <короткое название, по нему будет имя файла>
   ```
3. Закоммить и запушь в `main`.
4. Транскрипт появится в [`transcripts/`](transcripts/) после ближайшего воскресенья 22:00 МСК.
5. Если нужно прогнать сразу — Actions → Transcribe → Run workflow.

## Как это работает

1. **Cron** в [`.github/workflows/transcribe.yml`](.github/workflows/transcribe.yml) — `0 19 * * 0` (воскресенье 19:00 UTC = 22:00 МСК).
2. [`scripts/trigger_kaggle.py`](scripts/trigger_kaggle.py) проверяет, есть ли в `videos.yml` записи со `status: pending`. Если нет — выходит, Kaggle не дёргается.
3. Если есть — пушит kernel в Kaggle (`kaggle kernels push`), ждёт завершения.
4. Kernel ([`kaggle/transcribe.py`](kaggle/transcribe.py)) на GPU:
   - тянет актуальный `videos.yml` из этого репо (raw.githubusercontent),
   - для каждой `pending` записи: `yt-dlp` качает аудио → `faster-whisper large-v3` транскрибирует → пишет `.txt` и `.srt` в `/kaggle/working/transcripts/`,
   - складывает обновлённый `videos.yml` (со `status: done` и путями) в `/kaggle/working/`.
5. GHA забирает выводы (`kaggle kernels output`), перекладывает в репо, коммитит от имени `github-actions[bot]`.

## Секреты GitHub Actions

| Имя              | Значение                                  |
|------------------|-------------------------------------------|
| `KAGGLE_USERNAME`| `slawagromov`                             |
| `KAGGLE_KEY`     | значение `key` из свежего `kaggle.json`   |

Установка `KAGGLE_KEY` (без появления значения в терминале):
```bash
jq -r .key ~/Downloads/kaggle.json | gh secret set KAGGLE_KEY -R Slakwik/slakwik-sermons-subs
```
