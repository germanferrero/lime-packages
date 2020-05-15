import atexit
import shlex
import subprocess
import time

import pexpect
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

NODE_IP = "10.13.0.1"

def navigate_to_section(driver, section):
    menu = driver.find_element_by_tag_name("nav")

    if not menu.is_displayed():
        menu_btn = driver.find_element_by_css_selector("div[class^='hamburger']")
        menu_btn.click()
        assert menu.is_displayed()

     # wait until
    section_link = menu.find_element_by_link_text(section)
    section_link.click()

def get_element_center(element):
    center_x = element.location['x'] + element.size['width'] / 2
    center_y = element.location['y'] + element.size['height'] / 2
    return (center_x, center_y)

class QemuHandler:
    MONITOR_PORT = 45454
    STOP_TIMEOUT_S = 10
    MIN_BOOT_TIME_S = 2

    def __init__(self, start_args):
        self.console = None
        self.qemu_process = None
        self.start_args = start_args

    def start(self):
        if self.is_running():
            raise ValueError("Qemu is already running")
        qemu_start_cmd = f"sudo ./tools/qemu_dev_start --no-serial {self.start_args}"
        self.qemu_process = subprocess.Popen(shlex.split(qemu_start_cmd))
        atexit.register(self.stop)
        time.sleep(1)
        return self.qemu_process

    def stop(self):
        """
        Stop gracefully the qemu process, waiting until powerdown.
        """
        if not self.qemu_process:
            return
        if self.console:
            self.console.terminate()
        subprocess.run("./tools/qemu_dev_stop")
        try:
            self.qemu_process.communicate(timeout=self.STOP_TIMEOUT_S)
            self.qemu_process = None
        except subprocess.TimeoutExpired:
            print('Qemu did not terminate in time')

    def is_running(self):
        return self.qemu_process is not None

    def get_pexpect_console(self):
        if self.console is None:
            # telnet to the qemu telnet server into the serial console
            # not a telnet server running in the guest
            self.console = pexpect.spawn("telnet 127.0.0.1 45455", timeout=20)
            self.console.expect("Please press Enter to activate this console")
            self.console.sendline("")
            self.console.sendline("export PS1='prompt>>'")
            self.console.expect("prompt>>")
        return self.console


class WebdriverHandler:
    browser = None

    @classmethod
    def start(cls, disable_transitions=False):
        cls.browser = webdriver.Firefox()
        cls.browser.set_window_size(420, 720)
        return cls.browser

    @classmethod
    def stop(cls):
        cls.browser.quit()

def disable_css_transitions(browser):
    """Add a CSS rule that removes all transitions CSS"""
    # CSS transitions slows down the interaction
    script = """
    const styleElement = document.createElement('style');
    styleElement.setAttribute('id','style-tag');
    const styleTagCSSes = document.createTextNode('*,:after,:before{-webkit-transition:none!important;-moz-transition:none!important;-ms-transition:none!important;-o-transition:none!important;transition:none!important;}');
    styleElement.appendChild(styleTagCSSes);
    document.head.appendChild(styleElement);
    """
    browser.execute_script(script)

def wait_until_css_selector(selector):
    WebDriverWait(browser, 10).until(lambda x: browser.find_element_by_css_selector(selector))

def wait_until_xpath_selector(selector):
    return WebDriverWait(browser, 10).until(lambda x: browser.find_element_by_xpath(selector))

def test_lime_app_map():
    browser.get(f"http://{NODE_IP}")
    # Wait for the app to load
    WebDriverWait(browser, 10).until(EC.title_is("LiMe"))
    disable_css_transitions(browser)
    time.sleep(8)  # give some more time to load the multiple requests, TODO wait for some event

    # Close the FirstBootWizard splash
    fbw_btn_cancel = browser.find_elements_by_tag_name("button")[1]
    assert fbw_btn_cancel.text == 'CANCEL'
    fbw_btn_cancel.click()

    navigate_to_section(browser, 'Map')
    # As this node has not been located yet. A locate my node shows button shows up
    locate_my_node_btn = wait_until_xpath_selector('//button[text()="locate my node"]')
    locate_my_node_btn.click()
    # A location-marker should show up in the middle of the map
    location_marker = wait_until_xpath_selector('//*[@id="location-marker"]')
    map_div = browser.find_element_by_id('map-container')
    map_center_x, map_center_y = get_element_center(map_div)
    marker_center_x, marker_center_y = get_element_center(location_marker)
    # ignore rounding issues
    assert (abs(map_center_x - marker_center_x) <= 1)
    assert (abs(map_center_y - marker_center_y) <= 1)
    confirm_location_btn = wait_until_xpath_selector('//button[text()="confirm location"]')
    confirm_location_btn.click()

    # go out of the map and come back
    navigate_to_section(browser, "Status")
    navigate_to_section(browser, "Map")

    # Now it should shows the node in the middle of the screen
    node_marker = wait_until_xpath_selector('//img[@alt="node marker"]')
    marker_center_x, marker_center_y = get_element_center(node_marker)
    assert (abs(map_center_x - marker_center_x) <= 1)
    # Node marker is shown above node coords
    marker_bottom = marker_center_y + (node_marker.size['height'] / 2)
    assert (abs(map_center_y - marker_bottom) <= 1)
    # Now it shows a button to edit the location
    wait_until_xpath_selector('//button[text()="edit location"]')
    # TODO test community view

def test_lime_app_network_administration():
    browser.get(f"http://{NODE_IP}")
    # Wait for the app to load
    WebDriverWait(browser, 10).until(EC.title_is("LiMe"))
    disable_css_transitions(browser)
    wait_until_xpath_selector('//button[text()=cancel]')

    # Close the FirstBootWizard splash
    fbw_btn_cancel = browser.find_elements_by_tag_name("button")[1]
    assert fbw_btn_cancel.text == 'CANCEL'
    fbw_btn_cancel.click()

    # Open the menu
    menu = browser.find_element_by_tag_name("nav")
    assert not menu.is_displayed()

    menu_btn = browser.find_element_by_css_selector("div[class^='hamburger']")
    menu_btn.click()
    assert menu.is_displayed()

    # Go to the network configuration
    network_configuration_link = menu.find_element_by_link_text("Network Configuration")
    network_configuration_link.click()

    # fill the input password
    password_input = browser.find_element_by_css_selector("input[name='password']")
    password_input.send_keys("anypassword")  # this asumes starting without password
    login_btn = browser.find_element_by_css_selector("button")
    assert login_btn.text == "LOGIN"

    login_btn.click()
    # This lead us to the network configuration

    # wait for the login to complete
    wait_until_css_selector("input[placeholder='Password']")

    password_input = browser.find_element_by_css_selector("input[placeholder='Password']")
    re_enter_password = browser.find_element_by_css_selector(
        "input[placeholder='Re-enter Password']")

    change_btn = browser.find_element_by_xpath("//div[@class='container']/*/button")
    assert not change_btn.is_enabled()

    password_input.send_keys("123")
    assert not change_btn.is_enabled()

    re_enter_password.send_keys("123")
    assert not change_btn.is_enabled()

    password_input.send_keys("a123456789")
    assert not change_btn.is_enabled()

    re_enter_password.send_keys("a123456789")
    change_btn.is_enabled()
    change_btn.click()

    WebDriverWait(browser, 10).until(lambda x: 'Shared Password changed successfully' in
                                               browser.find_element_by_class_name("container").text)

    # go to Status and back
    navigate_to_section(browser, "Status")
    navigate_to_section(browser, "Network Configuration")

    password_input = browser.find_element_by_css_selector("input[name='password']")

    password_input.send_keys("not the password 123")
    login_btn = browser.find_element_by_css_selector("button")
    login_btn.click()
    assert "Wrong password, try again" not in browser.find_element_by_class_name("container").text
    
    password_input.clear()
    password_input.send_keys("a123456789")
    login_btn.click()
    WebDriverWait(browser, 10).until(lambda x: 'Change Shared Password' in
                                              browser.find_element_by_class_name("container").text)



rootfs = "/home/gf/Downloads/librerouteros-v1.2-x86-64-generic-rootfs.tar.gz"
ramfs = "/home/gf/Downloads/librerouteros-v1.2-x86-64-ramfs.bzImage"
start_args = f"--libremesh-workdir . {rootfs} {ramfs}"
qemu = QemuHandler(start_args=start_args)
qemu.start()
console = qemu.get_pexpect_console()
console.sendline("uname -a")
console.expect("GNU/Linux")

browser = WebdriverHandler.start()

# test_lime_app_network_administration()
test_lime_app_map()

WebdriverHandler.stop()
qemu.stop()
