import socket

def port_scan(ip,port):
    try:
        s = socket.socket(socket.AF_INET,socket.SOCK_STREAM) #创建基于tpc的套接字
        s.settimeout(1)#设置超时时间
        s.connect((ip,port)) #连接服务器
        print("[+]{}:{} \t open".format(ip,port))
        s.close()
    except socket.error as e:
        print("[-]{}:{} \t closed".format(ip, port))

    except Exception as e:
        print(e)

def scan_ports(ip, port_input):
    #检测是否为单个端口或者多个端口，多个端口可以使用逗号进行分隔
    if ',' not in port_input and port_input.isdigit():
        #如果是单个端口，直接扫描
        port_scan(ip,int(port_input))
    elif ',' in port_input:
        ports = list()
        port_strings = port_input.split(",")
        for port_string in port_strings:
            #检测当前的字符串是否全部是字符串组成
            if port_string.isdigit():
                ports.append(int(port_string))
        for port in ports:
            port_scan(ip,port)
if __name__ == "__main__":
    # ip = input("请输入要扫描的IP地址：")
    # port_range = input("请输入端口的范围（1-100）或者1:100：")
    # scan_ports(ip,port_range)
    while True:
        ip  = input("请输入ip地址：").strip().lower()
        if ip in ('q','quit'):
            print("退出程序")
            break
        if not ip:
            print("ip地址不能为空,请重新输入")
            continue

        port_input = input(
            "请输入端口号:").strip().lower()
        if port_input in ('q','quit'):
            print("退出程序")
            break
        if not port_input:
            print("端口号不能为空，请重新输入")
            continue

        scan_ports(ip,port_input)
