#!/usr/bin/env python3

from subprocess import getoutput
import os

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk as gtk

from pppoediplugin.CheckConnection import CheckConnection
from pppoediplugin.Settings import Settings

import dbus
from dbus.mainloop.glib import DBusGMainLoop
import sys
import threading
import time

class PppoeDi(object):
    def __init__(self):
        object.__init__(self)
        builder = gtk.Builder()
        builder.add_from_file('/usr/share/pppoedi/pppoedi.glade')
        self.window = builder.get_object("main_window")
        self.entry_login = builder.get_object("entry_login")
        self.entry_password = builder.get_object("entry_password")
        self.status = builder.get_object("status")
        self.checkbutton_savepass = builder.get_object("checkbutton_savepass")
        self.window.show()
        builder.connect_signals({"gtk_main_quit": self.quit_pppoe,
                                 "on_entry_login_activate": self.connect,
                                 "on_entry_password_activate": self.connect,
                                 "on_button_connect_clicked": self.connect,
                                 "on_button_disconnect_clicked":
                                     self.disconnect})
        self.pap_secrets_file = '/etc/ppp/pap-secrets'

        self.set_distro()
        self.verify_saved_password()
        self.settings = Settings()
        check_conn = CheckConnection(self.status, self.settings)
        check_conn.start()
        self.initialize_dbus_session()
        self.initialize_pppoedi_bus()

    def initialize_pppoedi_bus(self):
        system_bus = dbus.SystemBus()
        try:
            self.pppoedi_bus = system_bus.get_object("com.lar.PppoeDi","/PppoeDiService")
            self.pppoedi_bus_interface = dbus.Interface(self.pppoedi_bus, "com.lar.PppoeDi")
        except dbus.DBusException as e:
            #TODO: add pop-up
            sys.exit(1)
    
    def initialize_dbus_session(self):
        DBusGMainLoop(set_as_default=True)
        session_bus = dbus.SessionBus()
        if self.linux_distro_type == 1:
            session=getoutput(['ps -A | egrep -i "gnome|kde|mate|cinnamon"'])
            if session.find('mate-session') != -1:
                session_bus.add_match_string("type='signal',interface='org.mate.ScreenSaver'")
            elif session.find('gnome-session') != -1:
                session_bus.add_match_string("type='signal',interface='com.ubuntu.Upstart0_6'")
            else:
                #TODO: add pop-up
                sys.exit(1)
        elif self.linux_distro_type == 2:
            session_bus.add_match_string("type='signal',interface='org.gnome.ScreenSaver'")
        session_bus.add_message_filter(self.filter_cb)

    def verify_saved_password(self):
        self.pppoe_file = os.getenv(
            'HOME') + '/.pppoedi.conf'
        # Define a localizacao do arquivo de configuraçao do PPPoE

        if os.path.isfile(self.pppoe_file):
            with open(self.pppoe_file) as login_pass:
                login_pass = login_pass.readline().split(",")

                if len(login_pass) > 1:
                    login = login_pass[0]
                    password = login_pass[1]
                    self.entry_login.set_text(login)
                    self.entry_password.set_text(password)
                    self.checkbutton_savepass.set_active(True)

    def set_distro(self):
        distro_name = ''  # Inicializa a variavel que armazena o nome da
        # distribuicao em uso

        # Le o nome da distribuicao em uso no arquivo '/etc/os-release' e
        # armazena na variavel 'distro_name'
        with open('/etc/os-release', 'r') as f:
            while 'NAME' not in distro_name:
                distro_name = f.readline()

        # Lista com as distribuicoes mais populares baseadas em Debian
        debian_like_distro = ('Ubuntu', 'Ubuntu Studio', 'Ubuntu MATE',
                              'Kubuntu', 'Xubuntu', 'Lubuntu', 'Linux Mint',
                              'Kali Linux', 'Zorin OS', 'deepin', 'LXLE',
                              'elementary OS', 'Bodhi Linux', 'Peppermint OS',
                              'siduction', 'Raspbian', 'Debian')

        # Lista com as distribuicoes mais populares baseadas em Fedora
        fedora_like_distro = ('Fedora', 'Red Hat Enterprise Linux', 'CentOS',
                              'ClearOS', 'Pidora')

        # Inicializa a variavel que armazena o tipo da distribuicao em uso
        # Assume o valor '1' se for baseada em Debian
        # Assume o valor '2' se for baseada em RHEL/Fedora
        self.linux_distro_type = 0

        # Procura cada item da lista de distros baseadas em Debian como
        # substring do nome da distro em uso
        if any(distro in distro_name for distro in debian_like_distro):
            self.linux_distro_type = 1
        # Procura cada item da lista de distros baseadas em RHEL/Fedora como
        # substring do nome da distro em uso
        elif any(distro in distro_name for distro in fedora_like_distro):
            self.linux_distro_type = 2
        else:
            exit(1)

    def quit_pppoe(self, widget):
        self.settings.quit_pppoedi = True

        if self.settings.connect_active:
            self.disconnect(widget)

        self.pppoedi_bus_interface.Exit()
        gtk.main_quit()

    def save_pass(self):
        login = self.entry_login.get_text()
        password = self.entry_password.get_text()

        with open(self.pppoe_file, 'w') as f:
            f.write(login + "," + password)

    def connect(self, widget):
        login = self.entry_login.get_text()
        password = self.entry_password.get_text()

        self.entry_login.set_property("editable", False)
        self.entry_password.set_property("editable", False)

        route = getoutput('route -n')

        gw=route.split("\n")[2].split(' ')[9]
        net="200.137.66.0/24"
        self.pppoedi_bus_interface.RouteAddNetGw(net,gw)

        line='"'+login+'" * "'+password+'"'
        self.pppoedi_bus_interface.PrintToFile(line,self.pap_secrets_file)

        interface = route.split("\n")[2].split(' ')[-1]

        if self.linux_distro_type == 1:  # Se a distro e baseada em Debian
            peer_lar="/etc/ppp/peers/lar"
            config_peer='noipdefault\ndefaultroute\nreplacedefaultroute\n' + \
                        'hide-password\nnoauth\npersist\nplugin rp-pppoe.' + \
                        'so '+interface+'\nuser "'+login+'"\nusepeerdns'
            self.pppoedi_bus_interface.PrintToFile(config_peer,peer_lar)
            interface="lar"
            self.pppoedi_bus_interface.Pon(interface)
        elif self.linux_distro_type == 2:  # Se a distro e baseada em
            # RHEL/Fedora
            peer_lar="/etc/sysconfig/network-scripts/ifcfg-ppp"
            config_peer='USERCTL=yes\nBOOTPROTO=dialup\nNAME=DSLppp0\nDEV' + \
                        'ICE=ppp0\nTYPE=xDSL\nONBOOT=no\nPIDFILE=/var/run' + \
                        '/pppoe-adsl.pid\nFIREWALL=NONE\nPING=.\nPPPOE_TI' + \
                        'MEOUT=80\nLCP_FAILURE=3\nLCP_INTERVAL=20\nCLAMPM' + \
                        'SS=1412\nCONNECT_POLL=6\nCONNECT_TIMEOUT=60\nDEF' + \
                        'ROUTE=yes\nSYNCHRONOUS=no\nETH='+interface+'\nPR' + \
                        'OVIDER=DSLppp0\nUSER='+login+'\nPEERDNS=no\nDEMAND=no'
            self.pppoedi_bus_interface.PrintToFile(config_peer,peer_lar)
            interface="ppp0"
            self.pppoedi_bus_interface.Ifup(interface)
            self.pppoedi_bus_interface.RouteAddDefault(interface)

        self.status.set_from_icon_name("network-idle",
                                             gtk.IconSize.BUTTON)

        self.settings.active_status = False
        self.settings.time_sleep = 3
        self.settings.connect_active = True

        if self.checkbutton_savepass.get_active():
            self.save_pass()

    def disconnect(self, widget):
        self.entry_login.set_property("editable", True)
        self.entry_password.set_property("editable", True)
        self.pppoedi_bus_interface.FileBlank(self.pap_secrets_file)

        if self.linux_distro_type == 1:
            interface="lar"
            self.pppoedi_bus_interface.Poff(interface)
        elif self.linux_distro_type == 2:
            interface="ppp0"
            self.pppoedi_bus_interface.Ifdown(interface)

        self.status.set_from_icon_name("network-offline",
                                             gtk.IconSize.BUTTON)

        self.settings.connect_active = False

    def main(self):
        gtk.main()

    def filter_cb(self, bus, message):
        if not (message.get_member() == "EventEmitted" or message.get_member() ==
                'ActiveChanged'):
            return
    
        args = message.get_args_list()
    
        if args[0] == "desktop-lock" or args[0] == True:
            self.disconnect(None)