from pprint import pprint

import requests, csv
from functions import write_spread_sheet, format_range_to_date, convert_to_google_date


def tracking_report(query_url, month, year, access_token, result_spread):
    cookies = {
        '_ga': 'GA1.2.953492404.1725863733',
        '_gid': 'GA1.2.1243740957.1725863733',
        '_ym_uid': '1725863733367004419',
        '_ym_d': '1725863733',
        '_ym_isad': '1',
        '_ym_visorc': 'w',
        'access_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzI1ODY0MTI4LCJpYXQiOjE3MjU4NjM4MjgsImp0aSI6ImIxMzEyZThlMTcwMTRjZDY4ZjU1MmMzM2M0ZTJjZTAxIiwidXNlcl9pZCI6MjI5Mn0.sF6Jj87SqfMChhb8LoRwTnldVCx1OofrlDc2-gVtLwk',
        'refresh_token': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTcyODQ1NTgyOCwiaWF0IjoxNzI1ODYzODI4LCJqdGkiOiIzM2Q4MWE3OTg2YTY0OTkzYmMxYzg5OGZhYmVjYzE1MSIsInVzZXJfaWQiOjIyOTJ9.jNG1oChTYSkR9iz-cgXsq8IHICmP6YJpmjKtzzEKdEg',
        'token_expires_at': '2024-09-09T09%3A42%3A08%2B03%3A00',
        'refresh_token_expires_at': '%222024-10-09T06%3A37%3A08.701Z%22',
        'rb-can-use': '1',
        '_gat_UA-62963573-1': '1',
        '_ga_DNPXG3ZVNV': 'GS1.2.1725863733.1.1.1725863843.60.0.0',
    }

    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'ru-RU',
        'authorization': f'Bearer {access_token}',
        # 'cookie': '_ga=GA1.2.953492404.1725863733; _gid=GA1.2.1243740957.1725863733; _ym_uid=1725863733367004419; _ym_d=1725863733; _ym_isad=1; _ym_visorc=w; access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzI1ODY0MTI4LCJpYXQiOjE3MjU4NjM4MjgsImp0aSI6ImIxMzEyZThlMTcwMTRjZDY4ZjU1MmMzM2M0ZTJjZTAxIiwidXNlcl9pZCI6MjI5Mn0.sF6Jj87SqfMChhb8LoRwTnldVCx1OofrlDc2-gVtLwk; refresh_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTcyODQ1NTgyOCwiaWF0IjoxNzI1ODYzODI4LCJqdGkiOiIzM2Q4MWE3OTg2YTY0OTkzYmMxYzg5OGZhYmVjYzE1MSIsInVzZXJfaWQiOjIyOTJ9.jNG1oChTYSkR9iz-cgXsq8IHICmP6YJpmjKtzzEKdEg; token_expires_at=2024-09-09T09%3A42%3A08%2B03%3A00; refresh_token_expires_at=%222024-10-09T06%3A37%3A08.701Z%22; rb-can-use=1; _gat_UA-62963573-1=1; _ga_DNPXG3ZVNV=GS1.2.1725863733.1.1.1725863843.60.0.0',
        'priority': 'u=1, i',
        'referer': 'https://rubrain.com/account/managers/time-tracking?month=2024-08-03&status=notReport&status=overtime',
        'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    }

    params = {
        'month': str(month),
        'year': str(year),
        'type': 'monthly',
    }

    sheet = f"{params['month']}-{params['year']}"

    object = None
    # try:
    response = requests.get(
        query_url,
        params=params,
        cookies=cookies,
        headers=headers,
    )
    response.raise_for_status()
    object = response.json()
    print('трекинг получен')

    # except requests.exceptions.HTTPError as e:
    #     print('Ошибка при выполнении запроса:', e)

    tracking_rows = [
        ['developer', 'project_id', 'project_name', 'created', 'date', 'description', 'hours', 'hours_norma',
         'hours_summary', 'minutes', 'modified', 'report_type', 'status']]

    for spec_report in object['data']:

        for date in spec_report['dates'].items():
            tracking_row = []

            for record in date[1]['records']:
                tracking_record = []
                first_name = str(spec_report['specialist']['freelancer']['first_name'])
                last_name = str(spec_report['specialist']['freelancer']['last_name'])
                full_name = f'{last_name} {first_name}'
                tracking_record.append(full_name)
                tracking_record.append(spec_report['specialist']['project']['id'])
                tracking_record.append(spec_report['specialist']['project']['name'])
                tracking_record.append(record['created'])

                date_string = record['date']
                date_numeric = convert_to_google_date(date_string)
                tracking_record.append(date_numeric)

                if record['files']:
                    files_urls = ''
                    for file in record['files']:
                        files_urls += '\nhttps://rubrain.com' + file['file']
                    tracking_record.append(record['description'] + ' - ' + str(record['hours']) + 'h.' + files_urls)
                else:
                    tracking_record.append(record['description'] + ' - ' + str(record['hours']) + 'h.')
                tracking_record.append(record['hours'])
                tracking_record.append(record['hours_norma'])
                tracking_record.append(record['hours_summary'])
                tracking_record.append(record['minutes'])
                tracking_record.append(record['modified'])
                tracking_record.append(record['report_type'])
                tracking_record.append(record['status'])

                tracking_rows.append(tracking_record)

            if tracking_row:
                tracking_rows.append(tracking_row)


    # with open(f"../csv/tracking_reports/{params['month']}-{params['year']}.csv", 'w', encoding='utf8', newline='') as f:
    #     write = csv.writer(f, delimiter=';')
    #     write.writerows(tracking_rows)



    spread = result_spread
    write_spread_sheet(spread, sheet, tracking_rows)
    format_range_to_date(spread, sheet, "E:E")


if __name__ == '__main__':
    pass
