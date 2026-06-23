import os
import json
import uuid
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

_spreadsheet = None

def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        creds_dict = json.loads(os.getenv('GOOGLE_CREDENTIALS_JSON'))
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        _spreadsheet = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
    return _spreadsheet


# ────────────────────────────────────────
# データ読み書き（Googleスプレッドシート）
# ────────────────────────────────────────

def tasks_yomikomi():
    ws = get_spreadsheet().worksheet('タスク')
    rows = ws.get_all_values()
    if len(rows) <= 1:
        return []
    return [{'id': r[0], 'namae': r[1], 'icon': r[2]} for r in rows[1:] if r[0]]


def kiroku_yomikomi():
    ws = get_spreadsheet().worksheet('記録')
    result = []
    for r in ws.get_all_records():
        result.append({
            'hi':         r['hi'],
            'kanryo_ids': json.loads(r['kanryo_ids']) if r['kanryo_ids'] else [],
            'all_clear':  r['all_clear'] in (True, 'True', 'TRUE'),
            'taiju':      float(r['taiju']) if r['taiju'] else None,
            'coin_ids':   json.loads(r['coin_ids']) if r['coin_ids'] else [],
        })
    return result


def kiroku_hozon(kiroku_list):
    ws = get_spreadsheet().worksheet('記録')
    rows = [['hi', 'kanryo_ids', 'all_clear', 'taiju', 'coin_ids']]
    for k in kiroku_list:
        rows.append([
            k['hi'],
            json.dumps(k.get('kanryo_ids', []), ensure_ascii=False),
            str(k.get('all_clear', False)),
            k.get('taiju') if k.get('taiju') is not None else '',
            json.dumps(k.get('coin_ids', []), ensure_ascii=False),
        ])
    ws.clear()
    ws.update('A1', rows)


def profile_yomikomi():
    ws = get_spreadsheet().worksheet('プロフィール')
    records = ws.get_all_records()
    if not records:
        return {'shincho': 0, 'taiju_start': 0, 'taiju_mokuhyo': 0, 'coin_total': 0}
    r = records[0]
    return {
        'shincho':       float(r.get('shincho') or 0),
        'taiju_start':   float(r.get('taiju_start') or 0),
        'taiju_mokuhyo': float(r.get('taiju_mokuhyo') or 0),
        'coin_total':    int(r.get('coin_total') or 0),
    }


def profile_hozon(profile):
    ws = get_spreadsheet().worksheet('プロフィール')
    ws.clear()
    ws.update('A1', [
        ['shincho', 'taiju_start', 'taiju_mokuhyo', 'coin_total'],
        [
            profile.get('shincho', 0),
            profile.get('taiju_start', 0),
            profile.get('taiju_mokuhyo', 0),
            profile.get('coin_total', 0),
        ]
    ])


def today_str():
    return date.today().isoformat()


def today_kiroku_get(kiroku_list):
    return next((k for k in kiroku_list if k['hi'] == today_str()), None)


def renzoku_keisan(kiroku_list):
    renzoku = 0
    check_date = date.today()
    kiroku_hi_set = {k['hi'] for k in kiroku_list if k.get('all_clear')}
    while True:
        if check_date.isoformat() in kiroku_hi_set:
            renzoku += 1
            check_date -= timedelta(days=1)
        else:
            break
    return renzoku


def taiju_progress_keisan(profile, today_kiroku):
    start   = profile.get('taiju_start', 0)
    mokuhyo = profile.get('taiju_mokuhyo', 0)
    if start == 0 or mokuhyo == 0 or start <= mokuhyo:
        return 0
    current = today_kiroku.get('taiju') if today_kiroku else None
    if current is None:
        return 0
    progress = (start - current) / (start - mokuhyo) * 100
    return max(0, min(100, progress))


def chara_stage_keisan(progress):
    if progress >= 80:   return 4
    elif progress >= 60: return 3
    elif progress >= 40: return 2
    elif progress >= 20: return 1
    else:                return 0


def room_stage_keisan(coin_total):
    if coin_total >= 50:  return 4
    elif coin_total >= 30: return 3
    elif coin_total >= 20: return 2
    elif coin_total >= 10: return 1
    else:                  return 0


def message_sentaku(renzoku, all_clear, kanryo_count, total):
    if all_clear:
        if renzoku == 7:    return "1週間達成！🎉 本当にすごい！次のステップへ！"
        elif renzoku == 14: return "2週間！もうあすみさんの習慣だね🌟"
        elif renzoku == 3:  return "3日連続クリア！習慣になってきてるよ✨"
        elif renzoku % 7 == 0: return f"{renzoku}日連続！継続は力なり！🔥"
        else: return f"{renzoku}日連続クリア中！最高だよ！🔥"
    elif kanryo_count == 0:
        return "今日もできることからやってみよう😊"
    else:
        return f"{kanryo_count}/{total}個できた！一歩踏み出せたね！明日また頑張ろう✨"


def gohoubi_check(renzoku):
    gohoubi_list = [
        {'hi': 3,  'message': '3日連続クリア！🎁 今日は好きなドラマ1話見ていいよ📺'},
        {'hi': 7,  'message': '1週間クリア！🎁 お風呂に入浴剤を使っていいよ🛁'},
        {'hi': 14, 'message': '2週間クリア！🎁 今日は好きな時間に寝ていいよ😴'},
        {'hi': 30, 'message': '1ヶ月クリア！🎁 今日は一日ゴロゴロしていいよ🛋️'},
    ]
    for g in gohoubi_list:
        if renzoku == g['hi']:
            return g['message']
    return None


# ────────────────────────────────────────
# トップページ
# ────────────────────────────────────────

@app.route('/')
def top_page():
    profile, tasks, kiroku_list = profile_yomikomi(), tasks_yomikomi(), kiroku_yomikomi()
    today_kiroku = today_kiroku_get(kiroku_list)
    renzoku      = renzoku_keisan(kiroku_list)

    kanryo_ids     = today_kiroku['kanryo_ids'] if today_kiroku else []
    all_clear      = today_kiroku.get('all_clear', False) if today_kiroku else False
    taiju_nyuryoku = today_kiroku.get('taiju') if today_kiroku else None

    progress    = taiju_progress_keisan(profile, today_kiroku)
    chara_stage = chara_stage_keisan(progress)
    room_stage  = room_stage_keisan(profile.get('coin_total', 0))

    message = message_sentaku(renzoku, all_clear, len(kanryo_ids), len(tasks))
    gohoubi = gohoubi_check(renzoku) if all_clear else None

    if profile.get('taiju_start', 0) == 0:
        return redirect(url_for('profile_setup'))

    return render_template('index.html',
                           profile=profile,
                           tasks=tasks,
                           kanryo_ids=kanryo_ids,
                           all_clear=all_clear,
                           renzoku=renzoku,
                           message=message,
                           gohoubi=gohoubi,
                           chara_stage=chara_stage,
                           room_stage=room_stage,
                           coin_total=profile.get('coin_total', 0),
                           taiju_nyuryoku=taiju_nyuryoku,
                           today=today_str())


# ────────────────────────────────────────
# タスクチェック
# ────────────────────────────────────────

@app.route('/check/<task_id>', methods=['POST'])
def task_check(task_id):
    tasks, kiroku_list, profile = tasks_yomikomi(), kiroku_yomikomi(), profile_yomikomi()
    today_k = today_kiroku_get(kiroku_list)

    if today_k is None:
        today_k = {'hi': today_str(), 'kanryo_ids': [], 'all_clear': False,
                   'taiju': None, 'coin_ids': []}
        kiroku_list.append(today_k)

    if 'coin_ids' not in today_k:
        today_k['coin_ids'] = []

    was_all_clear = today_k.get('all_clear', False)

    if task_id in today_k['kanryo_ids']:
        today_k['kanryo_ids'].remove(task_id)
    else:
        today_k['kanryo_ids'].append(task_id)
        coin_key = f'task_{task_id}'
        if coin_key not in today_k['coin_ids']:
            today_k['coin_ids'].append(coin_key)
            profile['coin_total'] = profile.get('coin_total', 0) + 1

    today_k['all_clear'] = len(today_k['kanryo_ids']) == len(tasks)

    if today_k['all_clear'] and not was_all_clear:
        if 'all_clear_bonus' not in today_k['coin_ids']:
            today_k['coin_ids'].append('all_clear_bonus')
            profile['coin_total'] = profile.get('coin_total', 0) + 2

    kiroku_hozon(kiroku_list)
    profile_hozon(profile)
    return redirect(url_for('top_page'))


# ────────────────────────────────────────
# 体重入力
# ────────────────────────────────────────

@app.route('/taiju', methods=['POST'])
def taiju_nyuryoku():
    kiroku_list, profile = kiroku_yomikomi(), profile_yomikomi()
    today_k = today_kiroku_get(kiroku_list)

    taiju_str = request.form.get('taiju', '').strip()
    try:
        taiju = float(taiju_str)
    except ValueError:
        return redirect(url_for('top_page'))

    if today_k is None:
        today_k = {'hi': today_str(), 'kanryo_ids': [], 'all_clear': False,
                   'taiju': None, 'coin_ids': []}
        kiroku_list.append(today_k)

    if 'coin_ids' not in today_k:
        today_k['coin_ids'] = []

    today_k['taiju'] = taiju

    if 'taiju_input' not in today_k['coin_ids']:
        today_k['coin_ids'].append('taiju_input')
        profile['coin_total'] = profile.get('coin_total', 0) + 1

    kiroku_hozon(kiroku_list)
    profile_hozon(profile)
    return redirect(url_for('top_page'))


# ────────────────────────────────────────
# プロフィール設定
# ────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
def profile_setup():
    profile = profile_yomikomi()
    if request.method == 'POST':
        try:
            profile['shincho']       = float(request.form.get('shincho', 0))
            profile['taiju_start']   = float(request.form.get('taiju_start', 0))
            profile['taiju_mokuhyo'] = float(request.form.get('taiju_mokuhyo', 0))
        except ValueError:
            pass
        profile_hozon(profile)
        return redirect(url_for('top_page'))
    return render_template('profile.html', profile=profile)


# ────────────────────────────────────────
# タスク管理
# ────────────────────────────────────────

@app.route('/admin')
def kanri_page():
    tasks = tasks_yomikomi()
    return render_template('admin.html', tasks=tasks)


@app.route('/admin/task/tsuika', methods=['POST'])
def task_tsuika():
    namae = request.form.get('namae', '').strip()
    icon  = request.form.get('icon', '✅').strip()
    if namae:
        ws = get_spreadsheet().worksheet('タスク')
        ws.append_row([str(uuid.uuid4()), namae, icon])
    return redirect(url_for('kanri_page'))


@app.route('/admin/task/<task_id>/sakujo', methods=['POST'])
def task_sakujo(task_id):
    ws   = get_spreadsheet().worksheet('タスク')
    cell = ws.find(task_id)
    if cell:
        ws.delete_rows(cell.row)
    return redirect(url_for('kanri_page'))


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
