"""Check or explicitly sync the shared requirements between two project files."""
import argparse
import os
from pathlib import Path

START = '<!-- shared-requirements:start -->'
END = '<!-- shared-requirements:end -->'
ROOT = Path(__file__).resolve().parent.parent


def section(text):
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError('文件必须且只能包含一组共同要求标记')
    start = text.index(START)
    end = text.index(END)
    if end < start:
        raise ValueError('共同要求标记顺序不正确')
    return start, end + len(END)


def check(root):
    first = (root / 'AGENTS.md').read_bytes().decode('utf-8')
    second = (root / 'Workspace_Handoff.md').read_bytes().decode('utf-8')
    a, b = section(first)
    c, d = section(second)
    return first[a:b] == second[c:d]


def sync(root, source):
    files = {'agents': root / 'AGENTS.md', 'handoff': root / 'Workspace_Handoff.md'}
    if source not in files:
        raise ValueError('必须明确指定来源')
    target = 'handoff' if source == 'agents' else 'agents'
    original = files[target].read_bytes()
    source_text = files[source].read_bytes().decode('utf-8')
    target_text = original.decode('utf-8')
    a, b = section(source_text)
    c, d = section(target_text)
    updated = (target_text[:c] + source_text[a:b] + target_text[d:]).encode('utf-8')
    if updated == original:
        return False
    temporary = files[target].with_name(files[target].name + '.sync.tmp')
    try:
        # Exclusive creation avoids replacing an existing recovery file.
        with temporary.open('xb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if files[target].read_bytes() != original:
            temporary.unlink()
            raise ValueError('同步期间目标文件已变化；未覆盖，请重新核对')
        temporary.replace(files[target])
    except FileExistsError:
        raise ValueError('同步临时文件已存在，请先核查') from None
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return True


def main():
    parser = argparse.ArgumentParser(description='检查或按明确方向同步两个文件的共同要求')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true', help='只检查，不修改文件')
    action.add_argument('--from', dest='source', choices=['agents', 'handoff'], help='明确指定共同要求的来源文件')
    args = parser.parse_args()
    try:
        if args.check:
            if not check(ROOT):
                print('共同要求不一致；请先核对，再明确指定同步方向。')
                return 1
            print('共同要求一致。')
        else:
            changed = sync(ROOT, args.source)
            print('已同步共同要求。' if changed else '共同要求已一致，无需修改。')
        return 0
    except (OSError, ValueError, UnicodeError) as error:
        print('未能同步：' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
