import logging
import re
import requests
import os
from datetime import datetime, timedelta

noip_username = ''      # Your no-ip.com username/email
noip_password = ''      # Your no-ip.com password
noip_hostnames = ['']   # The host or hosts to update

if os.path.isfile('/run/secrets/noip-username'):
    with open('/run/secrets/noip-username', 'r') as noipuser:
        noip_username = noipuser.read()

if os.path.isfile('/run/secrets/noip-password'):
    with open('/run/secrets/noip-password', 'r') as noippass:
        noip_password = noippass.read()

if "NOIP_HOSTS" in os.environ:
    noip_hostnames = list(os.environ['NOIP_HOSTS'].split(','))

ip_cache_file = '/tmp/ip.noipy'
quarantine_file = '/tmp/quarantine.noipy'


logger = logging.getLogger('NoIpy')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
ch.setFormatter(formatter)
logger.addHandler(ch)

def get_external_ip():
    ip_resolvers = [
        'http://icanhazip.com/'
    ]

    for resolver in ip_resolvers:
        try:
            response = requests.get(resolver)
        except requests.exceptions.RequestException as e:
            logger.warning('Could not get IP, caught exception {}'.format(e))
            continue
        else:
            data = response.text
            break

    return data


def parse_data_to_ip(data):
    regex = re.compile('([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})')
    match = re.search(regex, data)
    return match.group(0)


def update_api(ip):
    api_url = 'https://dynupdate.no-ip.com/nic/update'
    user_agent = 'NoIpy ddns update client/0.0.1 christian@dotslashme.com'

    headers = {'user-agent': user_agent}
    payload = {'myip': ip, 'hostname': noip_hostnames}

    try:
        response = requests.get(
            api_url,
            headers=headers,
            params=payload,
            auth=(noip_username, noip_password)
        )
    except requests.exceptions.RequestException as e:
        logger.debug('Could not update API, caugh exception {}'.format(e))
    else:
        return response.text


def check_response(response, ip):
    if ip in response:
        process_success(response, ip)
    else:
        process_error(response)


def process_success(response, ip):
    with open(ip_cache_file, 'w') as fh:
        print(ip, end='', file=fh)

    logger.info('The job completed successfully')


def process_error(response):
    if 'nohost' in response:
        logger.warning(
            'There is no DNS record for one or more hostnames. Check config'
        )
    elif 'badauth' in response:
        logger.warning(
            'The supplied credentials seems to be invalid. Check config'
        )
    elif 'badagent' in response:
        logger.error(
            'This update agent has been banned, setting up quarantine'
        )
        quarantine_client()
    elif '!donator' in response:
        logger.warning(
            'Update operation not supported by your subscription'
        )
    elif 'abuse' in response:
        logger.error(
            'Abuse reported for this user, setting up quarantine'
        )
        quarantine_client()
    else:  # 911
        logger.warning(
            'The noip server has issues, setting temporary quarantine'
        )
        now = datetime.now()
        quarantined_until = now + timedelta(minutes=45)
        quarantine_client(str(quarantined_until))


def is_quarantined():
    if os.path.isfile(quarantine_file):
        if os.stat(quarantine_file).st_size == 0:
            return True
        else:
            with open(quarantine_file, 'r') as fh:
                quarantined_until = datetime.strptime(
                    fh.read(), '%Y-%m-%d %H:%M:%S.%f'
                )

            now = datetime.now()

            if quarantined_until < now:
                os.remove(quarantine_file)
                return False

            return True


def quarantine_client(time=None):
    with open(quarantine_file, 'w') as fh:
        if time is not None:
            print(time, end='', file=fh)


if __name__ == '__main__':
    if is_quarantined():
        logger.error('This client has been quarantined - exiting')
    else:
        data = get_external_ip()
        ip = parse_data_to_ip(data)
        if os.path.isfile(ip_cache_file):
            with open(ip_cache_file, 'r') as fh:
                if fh.read() == ip:
                    logger.info(
                        'Recorded IP is the same as current IP, no update'
                    )
                    exit()

        response = update_api(ip)
        check_response(response, ip)
