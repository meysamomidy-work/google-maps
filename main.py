import time
import pandas as pd
from glob import glob
import random
from turtle import distance
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from tqdm import tqdm
from webdriver_manager.chrome import ChromeDriverManager
import psutil
import gc
import os
import threading



def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def cleanup_memory():
    """Force garbage collection to free memory"""
    gc.collect()


def create_driver():
    """Create a new Chrome driver with memory-optimized settings"""
    chrome_options = Options()
    
    # Memory optimization settings
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-images")  # Don't load images to save memory
    chrome_options.add_argument("--disable-javascript")  # Disable JS if not needed
    chrome_options.add_argument("--memory-pressure-off")
    chrome_options.add_argument("--max_old_space_size=4096")  # Limit memory usage
    
    # Performance settings
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.maximize_window()
    return driver


def run(file):
    driver = create_driver()
    df = pd.read_excel(file)
    # df.drop(columns=['Zip Code', 'State'], inplace=True)
    df.drop_duplicates(inplace=True)
    # df = df[df["Unclaimed Status"] == True]
    state = file.split("\\")[-1].split("-")[0].split(".")[0]
    state = state.split("/")[-1]
    print(f"********* {state} started *********")
    url_count = 0
    for loc in tqdm(df["google maps url"]):
        website, phone = '', ''
        url_count += 1
        driver.get(loc)
        
        try:
            # website_selectors = 'div.rogA2c.ITvuef div.Io6YTe.fontBodyMedium'
            website_selectors = '//a[@data-tooltip="Open website"]'
            WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, website_selectors)))
            website = driver.find_element(By.XPATH, website_selectors).get_attribute('href')
            print(f"Website found : {website}")

        except:
            pass

        try:
            phone_selectors = '//button[@data-tooltip="Copy phone number"]'
            WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.XPATH, phone_selectors)))
            phone = driver.find_element(By.XPATH, phone_selectors).get_attribute('aria-label').replace('Call: ', '').replace('Phone: ', '')
            print(f"Phone found : {phone}")
        except:
            pass


        with open(f"{state}.csv", "a", encoding="utf-8") as f:
            f.write(f"{loc}|{website}|{phone}\n")
        
        cleanup_memory()
        if url_count % 10 == 0:
            print(f"Memory usage: {get_memory_usage():.1f} MB")
        
    driver.quit()

# run("reduced_crawled/Texas.csv")
# t1 = threading.Thread(target=run, args=("reduced_crawled/California.csv",))
# t2 = threading.Thread(target=run, args=("reduced_crawled/NewYork.csv",))
t3 = threading.Thread(target=run, args=("prepared_to_google.xlsx",))
# t4 = threading.Thread(target=run, args=("prepared_to_google/NY_1.xlsx",))
# t1.start()
# t2.start()
t3.start()
# t4.start()
# t1.join()
# t2.join()
t3.join()
# t4.join()
# //a[@data-tooltip="Open website"]
# //button[@data-tooltip="Copy phone number"]