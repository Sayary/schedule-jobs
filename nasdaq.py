import requests
import json
from datetime import datetime
import sys
from multiprocessing import Pool

EXCHANGE_FEE = 0.17
OPTION_FEE = 0.65
# in %
ANNUAL_RETURN_RATE_THRESHOLD = 20
# 1 + delta
POSSIBILITY_THRESHOLD = 0.7
EFFECTIVE_TAX_RATE = 0.35
DAYS_THRESHOLD = 35

ASSET_CLASS = "stocks"

DEFAULT_STOCK_LIST = [
  'AAPL', 
  'FB', 
  'MSFT', 
  'TSM',
  'DIS', 

  'AMD', 
  'V',

  'PDD',
  'BABA',
  'JD', 


]

TARGET_PRICE = {

  'TSLA': 360.0,
  'FB': 260.0,
  'MSFT': 210.0,
  'AAPL': 115.0,
  'PDD': 120.0,
  'TSM': 90,
  'JD': 80,
  'DIS' : 140.0,
  'AMD' : 75,
  'V': 208,
  'NIO': 17.0,
  'SQ': 160,
}

# The fields we care when print out
COLUMN_TEMPLATE = [
  'strike',
  'strike_pre',
  'p_Bid', 
  'p_Ask', 
  'p_Volume', 
# 'Delta', 
  'Possibility',
  # Premium($) collected by selling puts
  'Premium',
  'ROI',
  'Optimized ROI']

def get_field_template():
  output = ""
  for key in COLUMN_TEMPLATE:
    output += "%s" % str(key).ljust(15)
  return output


def simplify_record(stock, record):
  stock_upper_case = str(stock).upper()
  if stock_upper_case in TARGET_PRICE.keys():
    target_price = TARGET_PRICE[stock_upper_case]
    if float(record['strike']) < target_price:
      record['strike'] = "*"+ str(record['strike'])
  output = ""
  for key in COLUMN_TEMPLATE:
    value = record[key]
    if value == None:
      value = "0"
    output += "%s" % str(value).ljust(15)
  return output

def is_qualified(record, days_left):
  strike = float(record['strike'])
  put_bid = float(record['p_Bid'])
  put_ask = float(record['p_Ask'])
  delta = float(record['Delta'])
  put_volume = float(record['p_Volume'])

  # Add new field 'Possibility'
  possibility = 1 + delta
  record['Possibility'] = round(possibility, 3)
  # Add new field Premium
  returns = (put_bid * 100 - OPTION_FEE - EXCHANGE_FEE)
  record['Premium'] = round(returns, 3)
  # Add new field strike_real
  strike_real = (strike * 100.0 - returns) / 100.0
  record['strike_pre'] = round(strike_real, 3)

  # Add new field ROI
  capital_at_risk = strike * 100
  annual_return_rate = returns / capital_at_risk * (365 / days_left) * 100
  record['ROI'] =  round(annual_return_rate, 3)
  
  # Add new field Optimized ROI
  optimized_bid = (put_bid + put_ask) / 2
  optimized_returns = (optimized_bid * 100 - OPTION_FEE - EXCHANGE_FEE)
  optimized_annual_return_rate = optimized_returns / capital_at_risk * (365 / days_left) * 100
  record['Optimized ROI'] =  round(optimized_annual_return_rate, 3)

  # Check if qualify
  qualified = annual_return_rate > ANNUAL_RETURN_RATE_THRESHOLD
  if delta == 0.0 or possibility <= POSSIBILITY_THRESHOLD:
    return False
  return qualified

def persisit_string(output_file, message, print_log = True):
  output_file.write(message + "\n")
  if print_log:
    print(message)

def get_option_chain(stock):
  url = "https://api.nasdaq.com/api/quote/%s/option-chain?assetclass=%s&callput=put&money=all" %(stock, ASSET_CLASS)
  payload = {}
  headers = {
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.135 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
  }

  # Calculate current month
  response = requests.request("GET", url, headers=headers, data = payload)
  # json_data = json.loads(response.text.encode('utf8'))
  json_data = json.loads(response.text)
  current_month_data = get_option_chain_from_table(json_data)
  # Print last trade price info
  last_trade_info = json_data['data']['lastTrade']
  # print(last_trade_info)

  # Calculate next month
  next_month = json_data['data']['filterlist']['fromdate']['filter'][1]['value']
  from_date = next_month.split("|")[0]
  to_date = next_month.split("|")[1]
  url += "&fromdate=%s&todate=%s"%(from_date, to_date)
  response = requests.request("GET", url, headers=headers, data = payload)
  json_data = json.loads(response.text.encode('utf8'))
  next_month_data = get_option_chain_from_table(json_data)

  current_month_data.update(next_month_data)
  return current_month_data

def get_option_chain_from_table(response_json_data):
  option_chain_data = response_json_data['data']['table']
  columns = option_chain_data['headers']
  records = option_chain_data['rows']
  # print("Find records: %s"%len(records))
  results = dict()
  current_exipre_group_key = ""
  current_exipre_group_records = list()
  for row in records:
    expire_group = row['expirygroup']
    if expire_group != None and expire_group != "":
      # add last group
      if current_exipre_group_key != "":
        results[current_exipre_group_key] = current_exipre_group_records
      # update new group
      date = datetime.strptime(expire_group, "%B %d, %Y")
      current_exipre_group_key = date.strftime("%Y-%m-%d")
      current_exipre_group_records = list()
    else:
      current_exipre_group_records.append(row)

  # Add last group
  results[current_exipre_group_key] = current_exipre_group_records
  return results

def get_option_chain_greek(stock, record_id):
  url = "https://api.nasdaq.com/api/quote/%s/option-chain?assetclass=stocks&recordID=%s"%(stock, record_id)
  payload = {}
  headers = {
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.135 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'
  }

  response = requests.request("GET", url, headers=headers, data = payload)
  json_data = json.loads(response.text.encode('utf8'))
  option_chain_data = json_data['data']['optionChainPutData']
  greek_records = option_chain_data['optionChainGreeksList']
  return greek_records

def populate_stock_info(stock):
  file_name = "%s.txt"%stock
  # file_name = "final.txt"
  f = open(file_name, "w")

  # Print stock meta data
  stock_name_upper = str(stock).upper()
  stock_title_msg = "========== Stock: %s =========="%stock
  persisit_string(f, stock_title_msg)

  target_price_msg = ""
  if stock_name_upper not in TARGET_PRICE.keys():
    target_price_msg = "!!!!!!!!!! [WARNING] Please add target stock price for %s !!!!!!!!!"%stock_name_upper
    print(target_price_msg)
  else:
    target_price_msg = "Target Price: %s"%TARGET_PRICE[stock_name_upper]
  persisit_string(f, target_price_msg)
  results = get_option_chain(stock)
  for expire_group in results.keys():
    expired_date = datetime.strptime(expire_group, "%Y-%m-%d")
    days_left = (expired_date - datetime.now()).days + 1

    if days_left > DAYS_THRESHOLD or days_left <= 0:
      continue
    # Print Exipre group
    expire_group_msg = "Stock: %s Exipre Date: %s, Days Left: %s"%(stock_name_upper, expire_group, days_left)
    persisit_string(f, expire_group_msg)
    expire_group_msg_printed = False
    # Print field template
    persisit_string(f, get_field_template())
    option_chain_records = results[expire_group]
    for option_chain_record in option_chain_records:
      strike_price = option_chain_record['strike']
      put_bid = option_chain_record['p_Bid']
      put_ask = option_chain_record['p_Ask']
      record_id = option_chain_record['drillDownURL'].split("/")[-1]
      # Filter noise
      if put_bid == "--" or put_ask == "--" or option_chain_record['p_Last'] == "--" or option_chain_record['p_Volume'] == "--":
        continue
      greek_record = get_option_chain_greek(stock, record_id)
      for key in greek_record.keys():
        value = greek_record[key]['value']
        option_chain_record[key] = value
      qualified = is_qualified(option_chain_record, days_left)
      if qualified:
        record_string = simplify_record(stock, option_chain_record)
        persisit_string(f, record_string)
        # if "*" in record_string:
          # if not expire_group_msg_printed:
          #   print(expire_group_msg)
          #   print(get_field_template())
          #   expire_group_msg_printed = True
          # print(record_string)
  print("Finish populating info for stock %s"%stock)
  f.close()

def populate_stock_info_safe(stock):
  try:
    populate_stock_info(stock)
  except Exception:
    print("Failed to parse stock: %s"%stock)

if __name__ == "__main__":
  if len(sys.argv) == 1:
    for stock in DEFAULT_STOCK_LIST:
      populate_stock_info(stock)
    # with Pool(1) as p:
    #   p.map(populate_stock_info_safe, DEFAULT_STOCK_LIST)
  elif len(sys.argv) == 2:
    symbol = str(sys.argv[1])
    if "-" in symbol:
      ASSET_CLASS = symbol.split("-")[0]
      stock = symbol.split("-")[1]
    else:
      stock = symbol
    populate_stock_info(stock)
  else:
    pass

  
  print("Finished.")

