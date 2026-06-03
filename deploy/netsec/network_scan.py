import socket
import argparse #处理终端的参数
from concurrent.futures import ThreadPoolExecutor,as_completed
import ipaddress
import ssl
import time
import requests
import paramiko


def parse_ports(port_arg):
    '''
        解析80，443,1-100格式
    '''
    ports = []
    parts = port_arg.split(",")
    for part in parts:
        if "-" in part:
            start,end = map(int,part.split("-"))
            ports.extend(range(start,end+1))
        else:
            ports.append(int(part))
    return sorted(list(ports))

def scan_port(ip,port,timeout):
    '''
    描单个端口的函数
    :param ip:
    :param port:
    :param timeout:
    :return:
    '''
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            if s.connect_ex((ip,port)) == 0:
                return port
    except Exception:
        pass
    return None

def scan_host_ports(target_ip,ports,timeout,workers):
    '''

    :param target_ip: 需要扫描的ip地址
    :param ports: 需要扫描的端口号
    :param timeout: 超时时间
    :param workers: 需要使用的线程数
    :return:
    '''
    open_ports = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        #线程事务的处理提交
        future_to_port = {executor.submit(scan_port,target_ip,port,timeout):port for port in ports}
        for future in as_completed(future_to_port):
            result = future.result()
            if result is not None:
                open_ports.append(result)
    return  sorted(open_ports)

#发现网段内存活的主机
def is_host_alive(ip,timeout=1):
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect_ex((ip,80))
            return True
    except Exception:
        return False

def discover_hosts(network,timeout=1,workers=100):
    live_hosts = []
    try:
        network_obj = ipaddress.ip_network(network,strict=False)
        #排除网络地址和广播地址
        hosts_to_scan = [str(ip) for ip in network_obj.hosts()]
    except ValueError as e:
        print(f"无效的网段格式:{e}")
        return  []

    print(f"正在发现网段{network}中存活的主机...")
    print(f"共{len(hosts_to_scan)}个ip地址待检测，使用{workers}个线程")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_ip = {executor.submit(is_host_alive,str(ip),timeout):ip for ip in hosts_to_scan}
        for future in as_completed(future_to_ip):
            ip = future_to_ip[future]
            try:
                if future.result():
                    live_hosts.append(ip)
                    print(f"发现存活的主机:{ip}")
            except Exception as e:
                print(f"检测主机{ip}时出错：{e}")
    print(f"主机发现完成，共发现{len(live_hosts)}台存活主机。")
    return  live_hosts

def main():
    parser = argparse.ArgumentParser(description="一个支持网段扫描的多线程网络侦查工具")

    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("-t","--target",help="扫描单个目标ip或域名")
    target_group.add_argument("-n","--network",help="扫描整个网段，如192.168.1.0/24")

    parser.add_argument("-p","--ports",default="1-1024",help="端口的范围，如80,22,808，1-100")
    parser.add_argument("-w","--workers",type=int,default=100,help="并发线程数（默认100）")
    parser.add_argument("--timeout",type=float,default=0.5,help="连接的超时时间（秒）（默认：0.5）")

    args = parser.parse_args()
    ports_to_scan = parse_ports(args.ports)

    #扫描单个目标
    if args.target:
        try:
            target_ip = socket.gethostbyname(args.target)
            print(f"开始扫描目标：{args.target}({target_ip})")
            print("-" * 50)
            open_ports = scan_host_ports(target_ip,ports_to_scan,args.timeout,args.workers)

            print("-" * 50)
            if open_ports:
                print(f"扫描完成！发现{len(open_ports)}个开放端口：")
                for port in open_ports:
                    print(f"  {port}/tcp")
            else:
                print(f"扫描完成！未发现开放的端口。")
        except socket.gaierror:
            print(f"无法解析主机名:{args.target}")
            return
    elif args.network:
        print(f"开始扫描网段:{args.network}")
        live_hosts = discover_hosts(args.network,args.timeout,args.workers)

        if not live_hosts:
            print(f"网段内未发现存活的主机，扫描结束")
            return

        #对每台存活的主机进行扫描
        print(f"\n开始对{len(live_hosts)}台主机进行端口扫描...")
        print("-" * 60)

        for host in live_hosts:
            open_ports = scan_host_ports(host,ports_to_scan,args.timeout,args.workers)
            if open_ports:
                print(f" 发现开放端口：{open_ports}")
            else:
                print(f" 未发现开放端口")
            print("-" * 60)
        print("整个网段全部扫描完成")
def main1():
    parser = argparse.ArgumentParser(description="简单的指纹识别工具")
    parser.add_argument("-t","--target",required=True,help="目标ip")
    parser.add_argument("-p","--ports",required=True,help="端口列表")

    args = parser.parse_args()

    ports = [int(p) for p in args.ports.split(",")]
    print(f"开始识别{args.target}的服务指纹...")
    print("-" * 60)
    print(f"{'端口':<10}{'状态':<10}{'服务信息':<40}")
    print("-" * 60)

    for port in ports:
        banner = get_banner(args.target,port)
        status = "开放" if "失败" not in banner and "无" not in banner else "未知/过滤"
        print(f"{port:<10}{status:<10}{banner:<40}")
def get_banner(ip,port,timeout=2):
    try:
        sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip,port))

        banner=""
        #针对http/https的特殊处理
        if port in [80,443,8080,8843]:
            try:
                #发送一个简单的HTTP HEAD请求
                request = f"HEAD / HTTP/1.1\r\nHost:{ip}\r\n\r\n"
                sock.send(request.encode())
                response = sock.recv(1024).decode("utf-8",errors="ignore")
                #简单解析Server字段
                for line in response.split("\r\n"):
                    if line.lower().startswith("server"):
                        banner = line
                        break
            except:
                pass
        else:
            #普通端口尝试去接收数据
            try:
                banner = sock.recv(1024).decode("utf-8",errors="ignore").strip()
            except:
                pass
        sock.close()
        return banner if banner else "无 banner 信息"
    except Exception as e:
        return  f"连接失败：{str(e)}"

'''
    当我们发现了开放了80或者443端口，下一步通常是寻找登录后台入口，备份文件或者是敏感配置信息，这个工具利用字典进行暴力枚举
    核心原理：
        使用requests库发送http请求
        依据http的状态码（200,301,404）判断目录是不是存在的
        使用线程池加速扫描
'''
DEFAULT_DICT = ["admin","login","index.php","backup","db","config",".git","robots.txt","wp-admin"]

def scan_dir(url,path,timeout=2):
    target_url = f"{url}/{path}"
    try:
        resp = requests.get(target_url,timeout=timeout)
        status_code = resp.status_code

        #过滤掉404，通常正常的状态码信息200,301,302,303,403都值得关注
        if status_code in [200,301,302,403]:
            return path,status_code,len(resp.content)
        return None
    except:
        return None

USERS = ["root","admin","test","user"]
PASSWORDS = ["123456","password","admin","root","12345678","admin12"]
def ssh_bruteforce(ip,port,username,password,timeout=3):
    #建立ssh远程连接
    client = paramiko.SSHClient()
    #使用自动添加代理
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(hostname=ip,port=port,username=username,password=password,timeout=timeout)
        client.close()
        return True
    except Exception:
        return False

def main2():
    parser = argparse.ArgumentParser(description="web目录扫描器")
    parser.add_argument("-u","--url",required=True,help="目标url地址")
    parser.add_argument("-w","--wordlist",help="字典的文件路径（可选）")
    parser.add_argument("-t","--threads",type=int,default=50,help="默认线程数（50）")
    args = parser.parse_args()

    paths = DEFAULT_DICT
    if args.wordlist:
        try:
            with open(args.wordlist,"r") as f:
                paths = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"字典未找到:{args.wordlist}")
            return
    print(f"目标：{args.url}")
    print(f"加载字典条目：{len(paths)}")
    print(f"开始扫描...")
    print("-" * 50)

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        future_to_path = {executor.submit(scan_dir,args.url,path):path for path in paths}
        for future in as_completed(future_to_path):
            result = future.result()
            print(f"结果集:{result}")
            if result:
                path,code,size  = result
                color_code = "\033[92m" if code == 200 else "\033[93m"
                print(f"{color_code}[+]发现：/{path}(状态：{code}，大小：{size})\033[0m")
def main3():
    parser = argparse.ArgumentParser(description="ssh弱口令检测工具")
    parser.add_argument("-t", "--target", required=True, help="目标ip")
    parser.add_argument("-p", "--port",type=int, default=22,help="检测端口（默认22）")
    parser.add_argument("-U", "--users", help="用户字典文件")
    parser.add_argument("-P", "--passwords", help="密码字典文件")
    args = parser.parse_args()

    user_list = USERS
    pass_list = PASSWORDS

    print(f"开始对 {args.target}:{args.port}进行弱口令检测...")
    print(f"尝试组合数：{len(user_list) * len(pass_list)}")

    success = False
    #为了防止ip被封，最好使用少量的线程或者是单线程，实际上暴力破解也是串行
    for user in user_list:
        for pwd in pass_list:
            print(f"尝试：{user}/{pwd}",end="\r")
            if ssh_bruteforce(args.target,args.port,user,pwd):
                print(f"\n[+]成功发现弱口令->用户：{user}，密码：{pwd}")
                success=True
                break
        if success:break
    if not success:
        print(f"\n[-]未在字典中发现弱口令")

if __name__ == '__main__':
    # main()
    main3()
    # print(scan_dir("https://cloud.tencent.com", 2))

