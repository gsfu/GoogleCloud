from tda import auth, client
from tda.orders.equities import equity_buy_market, equity_sell_market
from tda.orders.common import Duration, Session
import config
import json
from datetime import datetime
import pandas as pd
import numpy as np
import schedule
import time
import talib


STOCK = 'IWM'

def auth_func():

    try:
        c = auth.client_from_token_file(config.token_path, config.api_key)
    except FileNotFoundError:
        from selenium import webdriver
        with webdriver.Chrome() as driver:
            c = auth.client_from_login_flow(
                driver, config.api_key, config.redirect_uri, config.token_path)
    
    return c


def place_order(c, order_type, shares):

    if order_type == 'buy':
        order_spec = equity_buy_market(STOCK, shares).set_session(
            Session.NORMAL).set_duration(Duration.DAY).build()
        c.place_order(config.account_id, order_spec)

    if order_type == 'sell':
        order_spec = equity_sell_market(STOCK, shares).set_session(
            Session.NORMAL).set_duration(Duration.DAY).build()
        c.place_order(config.account_id, order_spec)


def get_prices(c, end):

    # fetch price history using tda-api for HA and current
    r = c.get_price_history(STOCK,
                            period_type=client.Client.PriceHistory.PeriodType.DAY,
                            period=client.Client.PriceHistory.Period.ONE_DAY,
                            frequency_type=client.Client.PriceHistory.FrequencyType.MINUTE,
                            frequency=client.Client.PriceHistory.Frequency.EVERY_FIVE_MINUTES,
                            end_datetime=end,
                            need_extended_hours_data=True
                            )

    assert r.status_code == 200, r.raise_for_status()

    # parse json and get candles data
    y = r.json()
    y = y["candles"]
    y = json.dumps(y)
    data = pd.read_json(y)

    return data

def get_position(c):

    r = c.get_account(config.account_id, fields=c.Account.Fields.POSITIONS)
    assert r.status_code == 200, r.raise_for_status()

    y = r.json()
    y = json.dumps(y)
    df = pd.read_json(y)
    return df

def get_STOCKposition(c):
    
    c = auth_func()
    P = get_position(c)    
    number_of_elements = len(P['securitiesAccount'][5])
    PP = P['securitiesAccount'][5]
    if number_of_elements == 4:    
        
        LONG = PP[3]['longQuantity']
        SHORT = PP[3]['shortQuantity']
            
        return True, LONG, SHORT
        
    elif number_of_elements == 3: 
            LONG = 0
            SHORT = 0
            return False, LONG, SHORT


def heikin_ashi(data):    
    ha_close = (data['open'] + data['close'] + data['high'] + data['low']) / 4
    
    ha_open = [(data['open'].iloc[0] + data['close'].iloc[0]) / 2]
    for close in ha_close[:-1]:
        ha_open.append((ha_open[-1] + close) / 2)    
    ha_open = np.array(ha_open)

    elements = data['high'], data['low'], ha_open, ha_close
    ha_high, ha_low = np.vstack(elements).max(axis=0), np.vstack(elements).min(axis=0)
    
    return pd.DataFrame({
        'ha_open': ha_open,
        'ha_high': ha_high,    
        'ha_low': ha_low,
        'ha_close': ha_close
    }) 


def get_cur_price(c):

    r = c.get_quote(STOCK)
    assert r.status_code == 200, r.raise_for_status()

    y = r.json()
    price = y[STOCK]["lastPrice"]

    return price

def get_action():

    c = auth_func()
    now = datetime.now()
    print(now)
    data = get_prices(c, now) 
    
    data['SAR'] = talib.SAR(data['high'], data['low'], 0.020)
    
    trim = heikin_ashi(data) 
    

    try:
        
        P = get_position(c)
        number_of_elements = len(P['securitiesAccount'][5])
        print("Number of elements in the list: ", number_of_elements)
        
        # get current position
        position,LONG, SHORT = get_STOCKposition(c)
        print('HAS POSITION: ' + str(position))
        print("Number of Long-position  is : ", LONG)
        print("Number of Short-position is : ", SHORT)
        
        print("-----")
        
        price = get_cur_price(c)
        print("Current     price " + str(price))
        
        currentSAR = data['SAR'][data.index[-2]]
        print("Current SAR price " + str(currentSAR))
       
        print("------------------")

        currentHAclose = trim['ha_close'][trim.index[-2]]
        print("CurrentHAclose price " + str(currentHAclose))
        currentHAopen = trim['ha_open'][trim.index[-2]]
        print("Current HAopen price " + str(currentHAopen))
        currentHAlow = trim['ha_low'][trim.index[-2]]
        print("Current  HAlow price " + str(currentHAlow))
        currentHAhigh = trim['ha_high'][trim.index[-2]]
        print("Current HAhigh price " + str(currentHAhigh))
        previousHAhigh = trim['ha_high'][trim.index[-3]]
        print("PreviousHAhigh price " + str(previousHAhigh))
        previousHAlow = trim['ha_low'][trim.index[-3]]
        print("Previous HAlow price " + str(previousHAlow))
        
        lastHAopen = trim['ha_open'][trim.index[-1]]
        print("Last   HAopen  price " + str(lastHAopen))      
        lastHAhigh = trim['ha_high'][trim.index[-1]]
        print("Last  HAhigh   price " + str(lastHAhigh))        
        lastHAlow = trim['ha_low'][trim.index[-1]]
        print("Last   HAlow   price " + str(lastHAlow))


        print("______________________________________________")

        
        if currentSAR > price: # Bear   

            if currentHAclose < currentHAopen:  #Red
                if currentHAopen == currentHAhigh:
                    if lastHAopen == lastHAhigh:
                        if position == False:
                            place_order(c, 'sell', 10)
                            print("SOLD") 
                        elif position == True:
                            if LONG != 0:
                                place_order(c, 'sell', LONG)
                                print("Flat_positions") 

            if currentHAhigh < price or (previousHAlow < currentHAlow and currentHAopen != currentHAhigh):
                    if position == True:
                        if SHORT != 0:
                            place_order(c, 'buy', SHORT)
                            print("close-BUY")
                        else:
                            place_order(c, 'sell', LONG)                    
                            print("Flat_positions")   
                          
     
        elif currentSAR < price: #Bull

                if currentHAclose > currentHAopen:  #Green
                    if currentHAopen == currentHAlow:
                        if lastHAopen == lastHAlow:
                            if position == False:
                                place_order(c, 'buy', 10)
                                print("BOUGHT")  
                            elif position == True:
                                if SHORT != 0:
                                    place_order(c, 'buy', SHORT)
                                    print("Flat_positions") 

                if currentHAlow > price or (previousHAhigh > currentHAhigh and currentHAopen != currentHAlow):      
                        if position == True:
                            if LONG != 0:
                                place_order(c, 'sell', LONG)
                                print("close-SELL")
                            else:
                                place_order(c, 'buy', SHORT)                    
                                print("Flat_positions")                     
     
    except:
        print('Auth Error')
        
        
# def schedule_everyday():
    
#     get_action()
#     schedule.every(30).seconds.until("15:00").do(get_action)
#     return schedule    
    

# def main():
#     #schedule.every(30).seconds.until("15:00").do(get_action)
#     schedule.every().day.at("08:36").do(schedule_everyday)
    
#     while True:
#         schedule.run_pending()
#         time.sleep(1)
        
# main()
        
def main():
    
    schedule.every(30).seconds.until("23:00").do(get_action)

    
    while True:
        schedule.run_pending()
        time.sleep(1)
        
main()