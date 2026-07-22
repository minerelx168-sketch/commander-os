#!/bin/bash
# Live E2E: consult the board + assign a real CMO task
set -e
H=http://localhost:8100
echo "== consult board (live LLM) =="
curl -s -m 180 -X POST "$H/api/consult" -H 'Content-Type: application/json' \
  -d '{"question":"ถ้าจะขยายธุรกิจตู้กดดอกไม้จากเอกมัยไปทองหล่อ เดือนหน้า มีความเสี่ยงและผลดีอะไรบ้าง"}' \
  | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('question:', j['question'][:60])
for k, a in j['answers'].items():
    print(f\"--- {k} [{a['provider']}] ok={a['ok']} ---\")
    print(a['text'][:220].replace(chr(10), ' / '))
"
echo
echo "== assign real CMO task (live) =="
curl -s -m 180 -X POST "$H/api/dept/cmo/task" -H 'Content-Type: application/json' \
  -d '{"command":"วางแผนโปรโมชั่นเปิดตัวตู้กดดอกไม้สาขาทองหล่อ ใช้งบ 5000 บาท 1 สัปดาห์"}' \
  | python3 -c "
import json, sys
t = json.load(sys.stdin)
print('task id:', t['id'], '| provider:', t['provider'])
print(t['result'][:400].replace(chr(10), ' / '))
"
echo
echo "== learning captured =="
curl -s "$H/api/dept/cmo/tasks" | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('tasks:', len(j['tasks']), '| lessons:', len(j['lessons']))
for l in j['lessons']:
    print('-', l[:150])
"
