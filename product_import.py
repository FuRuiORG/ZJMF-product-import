#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智简魔方(ZJMF)上游产品批量导入工具
Author: RuiNexus

功能:
- 登录后台获取会话
- 获取上游供货商列表
- 选择上游后获取其产品分组(一级/二级)
- 用户选择一级分组后批量导入
- 自动创建分组(带上游拼音首字母前缀)
- 导入后自动根据折扣创建客户分组
"""

import requests
import time
import json
import sys
import os
import re

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

try:
    from pypinyin import lazy_pinyin
    HAS_PYPINYIN = True
except ImportError:
    HAS_PYPINYIN = False


class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_banner():
    banner = f"""{Color.CYAN}{Color.BOLD}
╔══════════════════════════════════════════════╗
║   智简魔方 上游产品批量导入工具              ║
║   Author: RuiNexus                           ║
║   Version: 1.0.0                             ║
╚══════════════════════════════════════════════╝{Color.END}
"""
    print(banner)


def input_with_default(prompt, default=""):
    if default:
        result = input(f"{prompt} [{Color.YELLOW}{default}{Color.END}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def input_choice(prompt, options, allow_multi=False, allow_zero=False):
    for idx, label in options:
        print(f"  {Color.GREEN}[{idx}]{Color.END} {label}")

    hint = "请输入选项编号" + ("(多选用逗号分隔)" if allow_multi else "")
    while True:
        result = input(f"  {hint}: ").strip()
        if allow_multi:
            indices = []
            for part in result.split(","):
                part = part.strip()
                if part.isdigit():
                    indices.append(int(part))
            if allow_zero and 0 in indices:
                return [0]
            valid = all(any(idx == o[0] for o in options) for idx in indices)
            if valid and indices:
                return indices
            print(f"  {Color.RED}无效输入，请重新选择{Color.END}")
        else:
            if result.isdigit():
                idx = int(result)
                if allow_zero and idx == 0:
                    return 0
                if any(idx == o[0] for o in options):
                    return idx
            print(f"  {Color.RED}无效输入，请重新选择{Color.END}")


def confirm(prompt):
    result = input(f"{prompt} ({Color.GREEN}Y{Color.END}/{Color.RED}N{Color.END}): ").strip().upper()
    return result == "Y" or result == "YES"


def get_pinyin_initials(text):
    if HAS_PYPINYIN:
        try:
            initials = ""
            for char in text:
                if '\u4e00' <= char <= '\u9fff':
                    py = lazy_pinyin(char)
                    if py:
                        initials += py[0][0].upper()
                elif char.isalpha():
                    initials += char.upper()
            return initials
        except Exception:
            pass

    result = input_with_default(
        f"  {Color.YELLOW}无法自动转换拼音，请手动输入缩写{Color.END}",
        text[:2].upper()
    )
    return result


def calc_discount_rate(price, sale_price):
    if not price or float(price) <= 0:
        return 100
    if not sale_price or float(sale_price) <= 0:
        return 100

    price = float(price)
    sale_price = float(sale_price)

    if sale_price >= price:
        return 100

    rate = sale_price / price
    discount_pct = round(rate * 100)
    return discount_pct


class ZJMFImporter:
    def __init__(self):
        self.session = requests.Session()
        self.base_url = ""
        self.admin_path = ""
        self.username = ""
        self.password = ""
        self.upstreams = []
        self.upstream_products = None
        self.has_first_group_structure = False
        self.discount_groups = {}

    def _url(self, path):
        return f"{self.base_url}/{self.admin_path}/{path}"

    def _request_time(self):
        return str(int(time.time() * 1000))

    def _common_params(self):
        return {
            "request_time": self._request_time(),
            "languagesys": "CN"
        }

    def save_config(self, save_password=False):
        config = {
            "base_url": self.base_url,
            "admin_path": self.admin_path,
            "username": self.username
        }
        if save_password:
            config["password"] = self.password

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"  {Color.RED}保存配置失败: {e}{Color.END}")
            return False

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return None

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config
        except Exception as e:
            print(f"  {Color.YELLOW}加载配置失败: {e}{Color.END}")
            return None

    def delete_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                os.remove(CONFIG_FILE)
                return True
            except Exception:
                return False
        return True

    def login(self):
        print(f"\n{Color.BOLD}>>> 登录后台{Color.END}\n")

        saved_config = self.load_config()
        use_saved = False

        if saved_config:
            print(f"  {Color.CYAN}发现已保存的配置:{Color.END}")
            print(f"    网站地址: {saved_config.get('base_url', '')}")
            print(f"    后台路径: {saved_config.get('admin_path', '')}")
            print(f"    用户名: {saved_config.get('username', '')}")
            if saved_config.get('password'):
                print(f"    密码: {'*' * 8} (已保存)")
            else:
                print(f"    密码: (未保存)")

            use_saved = confirm("  是否使用已保存的配置?")

        if use_saved:
            self.base_url = saved_config.get("base_url", "").rstrip("/")
            self.admin_path = saved_config.get("admin_path", "")
            self.username = saved_config.get("username", "")
            saved_password = saved_config.get("password", "")

            if saved_password:
                self.password = saved_password
            else:
                self.password = input_with_default("密码")

            print(f"\n  使用配置: {self.base_url}/{self.admin_path}")
        else:
            self.base_url = input_with_default("网站后台地址(如 https://xxx.com)")
            self.base_url = self.base_url.rstrip("/")
            self.admin_path = input_with_default("后台路径(如 admin2024)")
            self.username = input_with_default("用户名")
            self.password = input_with_default("密码")

        if not HAS_PYPINYIN:
            print(f"\n  {Color.YELLOW}提示: 未安装 pypinyin，拼音转换将使用手动输入模式{Color.END}")
            print(f"  {Color.YELLOW}安装方法: pip install pypinyin{Color.END}\n")

        login_url = self._url("login")
        params = self._common_params()
        payload = {
            "username": self.username,
            "password": self.password,
            "captcha": ""
        }

        print(f"  正在登录 {self.base_url} ...")

        try:
            resp = self.session.post(
                login_url,
                params=params,
                json=payload,
                timeout=30,
                verify=False
            )

            cookies = self.session.cookies.get_dict()
            if not cookies.get("PHPSESSID") and not cookies.get("admin_username"):
                print(f"  {Color.RED}登录可能失败，未获取到有效Cookie{Color.END}")
                if not confirm("是否继续？"):
                    sys.exit(0)
            else:
                print(f"  {Color.GREEN}登录成功!{Color.END}")

                if not use_saved:
                    print(f"\n  {Color.CYAN}是否保存登录配置?{Color.END}")
                    print(f"    {Color.GREEN}[1]{Color.END} 保存(不含密码)")
                    print(f"    {Color.GREEN}[2]{Color.END} 保存(含密码) - {Color.YELLOW}注意: 密码明文存储{Color.END}")
                    print(f"    {Color.GREEN}[3]{Color.END} 不保存")

                    choice = input("  请选择: ").strip()
                    if choice == "1":
                        if self.save_config(save_password=False):
                            print(f"  {Color.GREEN}配置已保存到: {CONFIG_FILE}{Color.END}")
                    elif choice == "2":
                        if self.save_config(save_password=True):
                            print(f"  {Color.GREEN}配置已保存到: {CONFIG_FILE}{Color.END}")
                    else:
                        print(f"  {Color.YELLOW}未保存配置{Color.END}")

            if cookies.get("admin_username"):
                print(f"  管理员: {cookies['admin_username']}")
            return True

        except requests.exceptions.SSLError:
            print(f"  {Color.RED}SSL错误，请检查URL是否正确{Color.END}")
            sys.exit(1)
        except requests.exceptions.ConnectionError:
            print(f"  {Color.RED}连接失败，请检查URL是否正确{Color.END}")
            sys.exit(1)
        except Exception as e:
            print(f"  {Color.RED}登录异常: {e}{Color.END}")
            sys.exit(1)

    def get_upstreams(self):
        print(f"\n{Color.BOLD}>>> 获取上游列表{Color.END}\n")

        url = self._url("zjmf_finance_api")
        params = {
            **self._common_params(),
            "page": 1,
            "limit": 50,
            "orderby": "id",
            "sort": "desc"
        }

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") != 200:
                print(f"  {Color.RED}获取上游列表失败: {data.get('msg', '未知错误')}{Color.END}")
                sys.exit(1)

            self.upstreams = data["data"]["list"]

            if not self.upstreams:
                print(f"  {Color.YELLOW}没有可用的上游{Color.END}")
                sys.exit(0)

            print(f"  共找到 {len(self.upstreams)} 个上游:\n")

            options = []
            for i, up in enumerate(self.upstreams, 1):
                status_str = f"{Color.GREEN}正常{Color.END}" if up.get("status") == 1 else f"{Color.RED}停用{Color.END}"
                print(f"  {Color.GREEN}[{i}]{Color.END} "
                      f"{Color.BOLD}{up['name']}{Color.END} "
                      f"({up.get('type_zh', '')}) "
                      f"| {up['hostname']} "
                      f"| 产品数: {up.get('product_num', 0)} "
                      f"| 已导入: {up.get('set_product_num', 0)} "
                      f"| 状态: {status_str}")
                options.append((i, f"{up['name']} - {up['hostname']}"))

            return options

        except Exception as e:
            print(f"  {Color.RED}获取上游列表异常: {e}{Color.END}")
            sys.exit(1)

    def get_upstream_product_groups(self, upstream):
        print(f"\n{Color.BOLD}>>> 获取上游产品分组{Color.END}\n")

        hostname = upstream.get("hostname", "").rstrip("/")
        if not hostname:
            print(f"  {Color.RED}上游没有配置hostname{Color.END}")
            return None

        url = f"{hostname}/v1/products"
        up_username = upstream.get("username", "")
        up_password = upstream.get("password", "")

        print(f"  正在从上游获取产品: {url}")

        try:
            resp = requests.get(
                url,
                auth=(up_username, up_password),
                timeout=60,
                verify=False
            )
            data = resp.json()

            if data.get("status") != 200:
                print(f"  {Color.RED}获取上游产品失败: {data.get('msg', '未知错误')}{Color.END}")
                return None

            raw_data = data.get("data", [])

            if not raw_data:
                print(f"  {Color.YELLOW}该上游没有产品{Color.END}")
                return None

            if isinstance(raw_data, dict) and "first_group" in raw_data:
                self.upstream_products = raw_data["first_group"]
                self.has_first_group_structure = True
                print(f"  {Color.CYAN}检测到完整分组结构{Color.END}")
                print(f"  共有 {len(self.upstream_products)} 个一级分组:\n")

                for i, first_group in enumerate(self.upstream_products, 1):
                    second_groups = first_group.get("group", [])
                    product_count = sum(len(sg.get("products", [])) for sg in second_groups)
                    print(f"  {Color.GREEN}[{i}]{Color.END} "
                          f"{Color.BOLD}{first_group['name']}{Color.END} "
                          f"| 二级分组数: {len(second_groups)} "
                          f"| 产品数: {product_count}")

                    for j, sg in enumerate(second_groups[:3]):
                        sg_product_count = len(sg.get("products", []))
                        print(f"      └─ {sg['name']} ({sg_product_count} 个产品)")
                    if len(second_groups) > 3:
                        print(f"      └─ ... 还有 {len(second_groups) - 3} 个二级分组")
            else:
                self.upstream_products = raw_data if isinstance(raw_data, list) else []
                self.has_first_group_structure = False
                print(f"  {Color.CYAN}检测到扁平分组结构(仅二级分组){Color.END}")
                print(f"  共有 {len(self.upstream_products)} 个分组:\n")

                for i, group in enumerate(self.upstream_products, 1):
                    product_count = len(group.get("products", []))
                    print(f"  {Color.GREEN}[{i}]{Color.END} "
                          f"{Color.BOLD}{group['name']}{Color.END} "
                          f"| 产品数: {product_count}")

                    products = group.get("products", [])
                    for j, p in enumerate(products[:3]):
                        print(f"      - {p['name']} (ID: {p['id']})")
                    if product_count > 3:
                        print(f"      ... 还有 {product_count - 3} 个产品")

            return self.upstream_products

        except Exception as e:
            print(f"  {Color.RED}获取上游产品异常: {e}{Color.END}")
            return None

    def fetch_existing_discount_groups(self):
        url = self._url("product/productgroup")
        params = {
            **self._common_params(),
            "page": 1,
            "limit": 500,
            "sort": "desc"
        }

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                groups = data.get("list", [])
                self.discount_groups = {}
                for g in groups:
                    self.discount_groups[g["group_name"]] = g["id"]
                return True
        except Exception as e:
            print(f"  {Color.YELLOW}获取折扣分组失败: {e}{Color.END}")

        return False

    def get_first_group_id_by_name(self, name):
        url = f"{self.base_url}/v1/products"
        params = self._common_params()

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                raw_data = data.get("data", {})
                if isinstance(raw_data, dict) and "first_group" in raw_data:
                    groups = raw_data.get("first_group", [])
                    for g in groups:
                        if g.get("name") == name:
                            return g.get("id")
        except Exception as e:
            print(f"    {Color.YELLOW}查询一级分组失败: {e}{Color.END}")

        return None

    def create_first_group(self, name):
        url = self._url("save_product_first_group")
        params = self._common_params()

        payload = {
            "type": 1,
            "name": name,
            "headline": "",
            "tagline": "",
            "tpl_type": "default",
            "hidden": 0,
            "gid": 1,
            "alias": "",
            "is_upstream": 1
        }

        try:
            resp = self.session.post(url, params=params, json=payload, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                gid = None
                if "data" in data and isinstance(data["data"], dict):
                    gid = data["data"].get("id")
                elif "data" in data and isinstance(data["data"], int):
                    gid = data["data"]

                if gid:
                    print(f"    {Color.GREEN}创建一级分组成功: {name} (ID: {gid}){Color.END}")
                    return gid
                else:
                    print(f"    {Color.GREEN}创建一级分组成功: {name}{Color.END}")
                    print(f"    {Color.CYAN}正在查询新创建的一级分组ID...{Color.END}")
                    time.sleep(0.5)
                    gid = self.get_first_group_id_by_name(name)
                    if gid:
                        print(f"    {Color.GREEN}获取到一级分组ID: {gid}{Color.END}")
                        return gid
                    else:
                        print(f"    {Color.RED}无法获取一级分组ID{Color.END}")
                        return None
            else:
                print(f"    {Color.RED}创建一级分组失败: {data.get('msg', '未知错误')}{Color.END}")
                return None

        except Exception as e:
            print(f"    {Color.RED}创建一级分组异常: {e}{Color.END}")
            return None

    def get_second_group_id_by_name(self, name, first_group_id):
        url = f"{self.base_url}/v1/products"
        params = self._common_params()

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                raw_data = data.get("data", {})
                if isinstance(raw_data, dict) and "first_group" in raw_data:
                    first_groups = raw_data.get("first_group", [])
                    for fg in first_groups:
                        if fg.get("id") == first_group_id:
                            second_groups = fg.get("group", [])
                            for sg in second_groups:
                                if sg.get("name") == name:
                                    return sg.get("id")
        except Exception as e:
            print(f"    {Color.YELLOW}查询二级分组失败: {e}{Color.END}")

        return None

    def create_second_group(self, name, first_group_id):
        url = self._url("save_product_group")
        params = self._common_params()

        payload = {
            "type": 1,
            "name": name,
            "headline": "",
            "tagline": "",
            "order_frm_tpl": "default",
            "tpl_type": "default",
            "hidden": 0,
            "gid": first_group_id,
            "alias": "",
            "is_upstream": 1
        }

        try:
            resp = self.session.post(url, params=params, json=payload, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                gid = None
                if "data" in data and isinstance(data["data"], dict):
                    gid = data["data"].get("id")
                elif "data" in data and isinstance(data["data"], int):
                    gid = data["data"]

                if gid:
                    print(f"    {Color.GREEN}创建二级分组成功: {name} (ID: {gid}){Color.END}")
                    return gid
                else:
                    print(f"    {Color.GREEN}创建二级分组成功: {name}{Color.END}")
                    print(f"    {Color.CYAN}正在查询新创建的二级分组ID...{Color.END}")
                    time.sleep(0.5)
                    gid = self.get_second_group_id_by_name(name, first_group_id)
                    if gid:
                        print(f"    {Color.GREEN}获取到二级分组ID: {gid}{Color.END}")
                        return gid
                    else:
                        print(f"    {Color.RED}无法获取二级分组ID{Color.END}")
                        return None
            else:
                print(f"    {Color.RED}创建二级分组失败: {data.get('msg', '未知错误')}{Color.END}")
                return None

        except Exception as e:
            print(f"    {Color.RED}创建二级分组异常: {e}{Color.END}")
            return None

    def import_products(self, upstream_id, second_group_id, products, price_percent=100):
        url = self._url("zjmf_finance_api/inputproduct")
        params = self._common_params()

        form_data = {
            "gid": str(second_group_id),
            "upstream_price_value": str(price_percent),
            "ptype": "305",
            "zjmf_finance_api_id": str(upstream_id),
        }
        product_files = {}
        for p in products:
            key = f"productnames[{p['id']}]"
            product_files[key] = p["name"]

        form_data.update(product_files)

        try:
            resp = self.session.post(url, params=params, data=form_data, timeout=120, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                print(f"    {Color.GREEN}导入成功! 共导入 {len(products)} 个产品{Color.END}")
                return True
            else:
                print(f"    {Color.RED}导入失败: {data.get('msg', '未知错误')}{Color.END}")
                return False

        except Exception as e:
            print(f"    {Color.RED}导入异常: {e}{Color.END}")
            return False

    def ensure_discount_group(self, discount_pct, product_ids=None):
        group_name = str(discount_pct)

        if group_name in self.discount_groups:
            print(f"    折扣分组 '{group_name}' 已存在 (ID: {self.discount_groups[group_name]})")
            return self.discount_groups[group_name], True

        url = self._url("product/add_productgroup")
        params = self._common_params()

        payload = {
            "group_name": group_name,
            "pids": product_ids if product_ids else []
        }

        try:
            resp = self.session.post(url, params=params, json=payload, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                group_id = data.get("data", {}).get("id") if isinstance(data.get("data"), dict) else data.get("data")
                if group_id:
                    self.discount_groups[group_name] = group_id
                    print(f"    {Color.GREEN}创建折扣分组成功: {group_name} (ID: {group_id}){Color.END}")
                    return group_id, False

                print(f"    {Color.GREEN}创建折扣分组成功: {group_name}{Color.END}")
                print(f"    {Color.CYAN}正在查询新创建的折扣分组ID...{Color.END}")
                time.sleep(0.5)
                self.fetch_existing_discount_groups()
                if group_name in self.discount_groups:
                    group_id = self.discount_groups[group_name]
                    print(f"    {Color.GREEN}获取到折扣分组ID: {group_id}{Color.END}")
                    return group_id, False

            print(f"    {Color.RED}创建折扣分组失败: {data.get('msg', '未知错误')}{Color.END}")
            return None, False

        except Exception as e:
            print(f"    {Color.RED}创建折扣分组异常: {e}{Color.END}")
            return None, False

    def add_products_to_discount_group(self, group_id, group_name, product_ids):
        url = self._url("product/edit_productgroup")
        params = self._common_params()

        payload = {
            "id": group_id,
            "group_name": group_name,
            "pids": product_ids
        }

        try:
            resp = self.session.post(url, params=params, json=payload, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                print(f"    {Color.GREEN}已将 {len(product_ids)} 个产品添加到折扣分组 '{group_name}'{Color.END}")
                return True
            else:
                print(f"    {Color.RED}添加到折扣分组失败: {data.get('msg', '未知错误')}{Color.END}")
                return False

        except Exception as e:
            print(f"    {Color.RED}添加到折扣分组异常: {e}{Color.END}")
            return False

    def get_local_products(self):
        url = f"{self.base_url}/v1/products"
        params = self._common_params()

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                return data.get("data", {})
        except Exception as e:
            print(f"  {Color.YELLOW}获取本地产品列表失败: {e}{Color.END}")

        return None

    def get_product_discount(self, product_id):
        url = self._url("product/get_upstream_price")
        params = {
            **self._common_params(),
            "pid": product_id
        }

        try:
            resp = self.session.get(url, params=params, timeout=30, verify=False)
            data = resp.json()

            if data.get("status") == 200:
                flag = data.get("data", {}).get("flag", {})
                bates = flag.get("bates")
                if bates:
                    return float(bates)
        except Exception as e:
            print(f"    {Color.YELLOW}获取产品折扣失败 (ID: {product_id}): {e}{Color.END}")

        return None

    def process_discount_groups(self, imported_products):
        print(f"\n{Color.BOLD}>>> 处理折扣分组{Color.END}\n")

        print(f"  正在获取本地产品列表...")
        local_data = self.get_local_products()
        if not local_data:
            print(f"  {Color.YELLOW}无法获取本地产品列表，跳过折扣分组处理{Color.END}")
            return

        imported_names = {p["name"] for p in imported_products}
        local_products = []

        if isinstance(local_data, dict) and "first_group" in local_data:
            for fg in local_data.get("first_group", []):
                for sg in fg.get("group", []):
                    for p in sg.get("products", []):
                        if p.get("name") in imported_names:
                            local_products.append(p)
        elif isinstance(local_data, list):
            for g in local_data:
                for p in g.get("products", []):
                    if p.get("name") in imported_names:
                        local_products.append(p)

        if not local_products:
            print(f"  {Color.YELLOW}未找到已导入的产品{Color.END}")
            return

        print(f"  找到 {len(local_products)} 个已导入产品，正在获取折扣信息...\n")

        discount_map = {}

        for p in local_products:
            pid = p.get("id")
            pname = p.get("name")

            discount = self.get_product_discount(pid)
            if discount and discount < 100:
                discount_pct = int(round(discount))
                if discount_pct not in discount_map:
                    discount_map[discount_pct] = []
                discount_map[discount_pct].append(pid)
                print(f"    {pname}: {discount_pct}% 折扣")
            else:
                print(f"    {pname}: 无折扣")

        if not discount_map:
            print(f"\n  {Color.YELLOW}没有发现折扣产品{Color.END}")
            return

        print(f"\n  发现 {len(discount_map)} 种折扣:")
        for pct, pids in sorted(discount_map.items()):
            print(f"    {Color.CYAN}{pct}{Color.END}折: {len(pids)} 个产品")

        if not confirm("  是否开始创建折扣分组?"):
            return

        self.fetch_existing_discount_groups()

        for pct, pids in sorted(discount_map.items()):
            print(f"\n  处理 {pct} 折分组 ({len(pids)} 个产品):")
            group_id, needs_add = self.ensure_discount_group(pct, pids)
            if group_id and needs_add:
                self.add_products_to_discount_group(group_id, str(pct), pids)

    def run(self):
        print_banner()

        self.login()

        upstream_options = self.get_upstreams()

        print(f"\n{Color.BOLD}>>> 选择上游{Color.END}\n")
        selected = input_choice("请选择要导入的上游", upstream_options)
        upstream = self.upstreams[selected - 1]

        print(f"\n  已选择: {Color.BOLD}{upstream['name']}{Color.END} ({upstream['hostname']})")

        groups = self.get_upstream_product_groups(upstream)
        if not groups:
            sys.exit(0)

        print(f"\n{Color.BOLD}>>> 选择导入模式{Color.END}\n")
        print(f"  {Color.GREEN}[1]{Color.END} 按一级分组导入 - 选择一级分组，导入其下所有二级分组和产品")
        print(f"  {Color.GREEN}[2]{Color.END} 按二级分组导入 - 直接选择二级分组导入")

        mode = input_choice("请选择导入模式", [(1, "按一级分组导入"), (2, "按二级分组导入")])

        print(f"\n{Color.BOLD}>>> 选择要导入的分组{Color.END}\n")

        if mode == 1:
            if self.has_first_group_structure:
                print(f"  {Color.CYAN}请选择一级分组:{Color.END}\n")
                group_options = [(i, g["name"]) for i, g in enumerate(self.upstream_products, 1)]

                print(f"  {Color.YELLOW}输入 0 导入全部分组{Color.END}")
                selected_groups = input_choice("请选择一级分组(可多选)", group_options, allow_multi=True, allow_zero=True)

                if 0 in selected_groups:
                    selected_first_groups = self.upstream_products
                    print(f"\n  {Color.GREEN}将导入全部 {len(selected_first_groups)} 个一级分组{Color.END}")
                else:
                    selected_first_groups = [self.upstream_products[idx - 1] for idx in selected_groups]
                    print(f"\n  {Color.GREEN}将导入 {len(selected_first_groups)} 个一级分组:{Color.END}")
                    for fg in selected_first_groups:
                        print(f"    - {fg['name']}")

                for fg in selected_first_groups:
                    second_groups = fg.get("group", [])
                    if second_groups:
                        print(f"\n  {Color.CYAN}一级分组 '{fg['name']}' 下的二级分组:{Color.END}")
                        for sg in second_groups:
                            sg_product_count = len(sg.get("products", []))
                            print(f"    └─ {sg['name']} ({sg_product_count} 个产品)")
            else:
                print(f"  {Color.CYAN}检测到扁平结构，将创建一个一级分组包含选中的二级分组{Color.END}\n")
                group_options = [(i, g["name"]) for i, g in enumerate(self.upstream_products, 1)]
                print(f"  {Color.YELLOW}输入 0 导入全部分组{Color.END}")
                selected_second_indices = input_choice("请选择二级分组(可多选)", group_options, allow_multi=True, allow_zero=True)

                if 0 in selected_second_indices:
                    selected_second_groups = self.upstream_products
                    print(f"\n  {Color.GREEN}将导入全部 {len(selected_second_groups)} 个二级分组{Color.END}")
                else:
                    selected_second_groups = [self.upstream_products[idx - 1] for idx in selected_second_indices]
                    print(f"\n  {Color.GREEN}将导入 {len(selected_second_groups)} 个二级分组:{Color.END}")
                    for sg in selected_second_groups:
                        print(f"    - {sg['name']}")

                selected_first_groups = [{
                    "name": upstream["name"],
                    "group": selected_second_groups
                }]
        else:
            if self.has_first_group_structure:
                print(f"  {Color.CYAN}请选择二级分组:{Color.END}\n")
                all_second_groups = []
                for fg in self.upstream_products:
                    for sg in fg.get("group", []):
                        all_second_groups.append({
                            "name": sg["name"],
                            "products": sg.get("products", []),
                            "first_group_name": fg["name"]
                        })

                group_options = [(i, f"{sg['name']} (来自: {sg['first_group_name']})") for i, sg in enumerate(all_second_groups, 1)]
                print(f"  {Color.YELLOW}输入 0 导入全部分组{Color.END}")
                selected_second_indices = input_choice("请选择二级分组(可多选)", group_options, allow_multi=True, allow_zero=True)

                if 0 in selected_second_indices:
                    selected_second_groups = all_second_groups
                    print(f"\n  {Color.GREEN}将导入全部 {len(selected_second_groups)} 个二级分组{Color.END}")
                else:
                    selected_second_groups = [all_second_groups[idx - 1] for idx in selected_second_indices]
                    print(f"\n  {Color.GREEN}将导入 {len(selected_second_groups)} 个二级分组:{Color.END}")
                    for sg in selected_second_groups:
                        print(f"    - {sg['name']} (来自: {sg['first_group_name']})")

                first_group_map = {}
                for sg in selected_second_groups:
                    fg_name = sg["first_group_name"]
                    if fg_name not in first_group_map:
                        first_group_map[fg_name] = []
                    first_group_map[fg_name].append({
                        "name": sg["name"],
                        "products": sg["products"]
                    })

                selected_first_groups = []
                for fg_name, sg_list in first_group_map.items():
                    selected_first_groups.append({
                        "name": fg_name,
                        "group": sg_list
                    })
            else:
                print(f"  {Color.CYAN}请选择二级分组:{Color.END}\n")
                group_options = [(i, g["name"]) for i, g in enumerate(self.upstream_products, 1)]
                print(f"  {Color.YELLOW}输入 0 导入全部分组{Color.END}")
                selected_second_indices = input_choice("请选择二级分组(可多选)", group_options, allow_multi=True, allow_zero=True)

                if 0 in selected_second_indices:
                    selected_second_groups = self.upstream_products
                    print(f"\n  {Color.GREEN}将导入全部 {len(selected_second_groups)} 个二级分组{Color.END}")
                else:
                    selected_second_groups = [self.upstream_products[idx - 1] for idx in selected_second_indices]
                    print(f"\n  {Color.GREEN}将导入 {len(selected_second_groups)} 个二级分组:{Color.END}")
                    for sg in selected_second_groups:
                        print(f"    - {sg['name']}")

                selected_first_groups = [{
                    "name": upstream["name"],
                    "group": selected_second_groups
                }]

        if not confirm("\n  确认开始导入?"):
            print(f"  {Color.YELLOW}已取消{Color.END}")
            sys.exit(0)

        upstream_name = upstream["name"]
        py_initials = get_pinyin_initials(upstream_name)
        print(f"\n  上游 '{upstream_name}' 的拼音缩写: {Color.BOLD}{py_initials}{Color.END}")

        print(f"\n{Color.BOLD}{'='*50}{Color.END}")
        print(f"{Color.BOLD}>>> 开始导入产品{Color.END}")
        print(f"{Color.BOLD}{'='*50}{Color.END}\n")

        all_imported_products = []

        for first_group in selected_first_groups:
            first_group_name = first_group["name"]
            second_groups = first_group.get("group", [])

            if not second_groups:
                print(f"  {Color.YELLOW}一级分组 '{first_group_name}' 没有二级分组，跳过{Color.END}")
                continue

            new_first_group_name = f"{py_initials}-{first_group_name}"
            print(f"\n{Color.BOLD}{'='*40}{Color.END}")
            print(f"{Color.BOLD}处理一级分组: {first_group_name}{Color.END}")
            print(f"新一级分组名: {new_first_group_name}")
            print(f"{Color.BOLD}{'='*40}{Color.END}")

            first_group_id = self.create_first_group(new_first_group_name)
            if not first_group_id:
                print(f"  {Color.RED}无法创建一级分组，跳过该分组{Color.END}")
                continue

            for second_group in second_groups:
                second_group_name = second_group["name"]
                products = second_group.get("products", [])

                if not products:
                    print(f"\n  {Color.YELLOW}二级分组 '{second_group_name}' 没有产品，跳过{Color.END}")
                    continue

                print(f"\n  {Color.CYAN}处理二级分组: {second_group_name} ({len(products)} 个产品){Color.END}")

                second_group_id = self.create_second_group(second_group_name, first_group_id)
                if not second_group_id:
                    print(f"    {Color.RED}无法创建二级分组，跳过{Color.END}")
                    continue

                product_list = [{"id": p["id"], "name": p["name"]} for p in products]

                batch_size = 50
                total_imported = 0

                for i in range(0, len(product_list), batch_size):
                    batch = product_list[i:i + batch_size]
                    if self.import_products(upstream["id"], second_group_id, batch):
                        total_imported += len(batch)
                        all_imported_products.extend(batch)
                    else:
                        print(f"    {Color.RED}批次导入失败 (产品 {i+1}-{i+len(batch)}){Color.END}")
                        if not confirm(f"    是否继续导入下一批?"):
                            break

                print(f"    {Color.GREEN}二级分组 '{second_group_name}' 导入完成: {total_imported}/{len(product_list)} 个产品{Color.END}")

        if all_imported_products:
            print(f"\n{Color.BOLD}>>> 共导入 {len(all_imported_products)} 个产品{Color.END}")
            self.process_discount_groups(all_imported_products)

        print(f"\n{Color.CYAN}{Color.BOLD}{'='*50}{Color.END}")
        print(f"{Color.CYAN}{Color.BOLD}>>> 导入流程完成!{Color.END}")
        print(f"{Color.CYAN}{Color.BOLD}{'='*50}{Color.END}\n")


def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        importer = ZJMFImporter()
        importer.run()
    except KeyboardInterrupt:
        print(f"\n\n  {Color.YELLOW}用户中断操作{Color.END}")
        sys.exit(0)
    except Exception as e:
        print(f"\n  {Color.RED}程序异常: {e}{Color.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
