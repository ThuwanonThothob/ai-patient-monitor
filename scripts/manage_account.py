"""Provision named local accounts; passwords are entered privately and hashed."""
import argparse
import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / 'backend/.env')
os.environ.setdefault('WARD_DB_PATH', str(ROOT / 'backend/runtime/ward-demo.db'))
import auth
from patient_registry import PATIENT_PROFILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audience', nargs='?', choices=['staff', 'patient'], default=None,
                        help='Audience: staff or patient (optional with --list)')
    parser.add_argument('subject', nargs='?', default=None,
                        help='Named staff username, or patient ID')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', action='store_true', help='List accounts without displaying password hashes')
    group.add_argument('--disable', action='store_true', help='Disable the account and revoke its active sessions/push subscriptions')
    group.add_argument('--delete', action='store_true', help='Delete the account and revoke its active sessions/push subscriptions')
    args = parser.parse_args()

    auth.DB.parent.mkdir(parents=True, exist_ok=True)
    auth.init_sessions()

    if args.list:
        accounts = auth.list_accounts(args.audience)
        if not accounts:
            print('No accounts found.')
            return
        header = f"{'AUDIENCE':<10} {'SUBJECT':<15} {'STATUS':<10} {'TYPE':<10} {'DISPLAY NAME':<25} {'ROLE'}"
        print(header)
        print('-' * len(header))
        for acc in accounts:
            status = 'enabled' if acc['enabled'] else 'disabled'
            acc_type = 'test' if acc['is_test'] else 'standard'
            display = acc.get('display_name', '') or '-'
            role = acc.get('role', '') or '-'
            print(f"{acc['audience']:<10} {acc['subject']:<15} {status:<10} {acc_type:<10} {display:<25} {role}")
        return

    if not args.audience or not args.subject:
        parser.error('the following arguments are required: audience, subject')

    subject = args.subject.strip() if args.audience == 'staff' else args.subject.strip().upper()
    if args.audience == 'patient' and subject not in PATIENT_PROFILES:
        parser.error('Unknown patient ID')

    if args.disable:
        auth.disable_account(args.audience, subject)
        print(f'Account disabled: {args.audience}/{subject}. Active sessions and push subscriptions revoked. Database: {auth.DB}')
        return
    if args.delete:
        auth.delete_account(args.audience, subject)
        print(f'Account deleted: {args.audience}/{subject}. Active sessions and push subscriptions revoked. Database: {auth.DB}')
        return
    password = getpass.getpass('New password (at least 12 characters): ')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    try:
        auth.set_account(args.audience, subject, password)
    except ValueError as error:
        parser.error(str(error))
    print(f'Account ready: {args.audience}/{subject}. Previous sessions revoked. Database: {auth.DB}')


if __name__ == '__main__':
    main()

