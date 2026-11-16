import requests

# 1. 这里替换成你测试脚本里请求的那个接口地址（base_url + 具体的路径）
url = "http://192.168.1.71:13109/address/validate"

# 2. 这里替换成你测试用例里发送的请求数据（根据实际接口要求修改）
payload = {
    "address": "",
    "address2": "",
    "country": "Au",
    "order_id": "{% mock 'guid' %}",
    "postcode": "0800",
    "state": "NT",
    "suburb": "DARWIN CITY"
}

# 3. 如果接口需要 Token 或特定的请求头，在这里加上
headers = {
    "Content-Type": "application/json",
    # "Authorization": "Bearer 你的Token" 
}

print(f"正在请求接口: {url}")
print(f"发送的数据: {payload}")
print("-" * 30)

try:
    # 发送 POST 请求（如果是 GET 请求就把 post 改成 get，并把 json=payload 去掉）
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    
    print(f"状态码 (Status Code): {response.status_code}")
    print(f"响应头 (Headers): {dict(response.headers)}")
    print(f"响应内容 (Response): {response.text}")
    
    # 简单判断一下状态码是否在预期范围内
    if response.status_code in [200, 400]:
        print("\n✅ 状态码符合测试用例的预期范围 [200, 400]")
    else:
        print(f"\n❌ 状态码 {response.status_code} 不符合预期，这就是测试失败的原因！")

except requests.exceptions.RequestException as e:
    print(f"❌ 请求发生异常: {e}")
    print("（可能是接口地址写错了，或者本地/测试服务器没有启动）")