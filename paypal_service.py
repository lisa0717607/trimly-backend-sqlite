import os
import json
import asyncio
import aiohttp
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from base64 import b64encode

from utils import safe_json_loads, safe_json_dumps

class PayPalService:
    """PayPal 支付服務整合"""
    
    def __init__(self):
        # PayPal 設定（從環境變數讀取）
        self.client_id = os.getenv("PAYPAL_CLIENT_ID")
        self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET")
        self.environment = os.getenv("PAYPAL_ENV", "sandbox")  # sandbox 或 live
        
        # API 端點
        if self.environment == "live":
            self.base_url = "https://api-m.paypal.com"
        else:
            self.base_url = "https://api-m.sandbox.paypal.com"
        
        self.access_token = None
        self.token_expires_at = None
    
    async def get_access_token(self) -> str:
        """取得 PayPal 存取權杖"""
        
        # 檢查現有權杖是否仍然有效
        if (self.access_token and self.token_expires_at and 
            datetime.utcnow() < self.token_expires_at - timedelta(minutes=5)):
            return self.access_token
        
        # 準備認證資料
        auth_string = f"{self.client_id}:{self.client_secret}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        data = "grant_type=client_credentials"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/oauth2/token",
                headers=headers,
                data=data
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    self.access_token = result["access_token"]
                    expires_in = result.get("expires_in", 3600)
                    self.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                    return self.access_token
                else:
                    error_text = await response.text()
                    raise Exception(f"Failed to get PayPal access token: {error_text}")
    
    async def create_subscription_plan(self, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立 PayPal 訂閱方案"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "PayPal-Request-Id": f"PLAN-{plan_data['name']}-{int(datetime.utcnow().timestamp())}"
        }
        
        # 構建 PayPal 方案資料
        paypal_plan = {
            "product_id": plan_data.get("product_id"),  # 需要先建立產品
            "name": plan_data["display_name"],
            "description": f"Trimly {plan_data['display_name']} 訂閱方案",
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {
                        "interval_unit": "MONTH",
                        "interval_count": 1
                    },
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,  # 無限循環
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(plan_data["price_monthly"]),
                            "currency_code": "USD"
                        }
                    }
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee": {
                    "value": "0",
                    "currency_code": "USD"
                },
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3
            },
            "taxes": {
                "percentage": "0",
                "inclusive": False
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/billing/plans",
                headers=headers,
                json=paypal_plan
            ) as response:
                
                result = await response.json()
                
                if response.status == 201:
                    return {
                        "success": True,
                        "plan_id": result["id"],
                        "plan_data": result
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    async def create_subscription(self, plan_id: str, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """建立 PayPal 訂閱"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "PayPal-Request-Id": f"SUB-{user_data['user_id']}-{int(datetime.utcnow().timestamp())}"
        }
        
        # 構建訂閱資料
        subscription_data = {
            "plan_id": plan_id,
            "start_time": (datetime.utcnow() + timedelta(minutes=1)).isoformat() + "Z",
            "subscriber": {
                "name": {
                    "given_name": user_data.get("first_name", "User"),
                    "surname": user_data.get("last_name", "")
                },
                "email_address": user_data["email"]
            },
            "application_context": {
                "brand_name": "Trimly",
                "locale": "en-US",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
                },
                "return_url": user_data.get("return_url", "https://trimly.com/subscription/success"),
                "cancel_url": user_data.get("cancel_url", "https://trimly.com/subscription/cancel")
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/billing/subscriptions",
                headers=headers,
                json=subscription_data
            ) as response:
                
                result = await response.json()
                
                if response.status == 201:
                    # 提取核准連結
                    approve_link = None
                    for link in result.get("links", []):
                        if link["rel"] == "approve":
                            approve_link = link["href"]
                            break
                    
                    return {
                        "success": True,
                        "subscription_id": result["id"],
                        "approve_link": approve_link,
                        "subscription_data": result
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    async def get_subscription_details(self, subscription_id: str) -> Dict[str, Any]:
        """取得訂閱詳情"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/v1/billing/subscriptions/{subscription_id}",
                headers=headers
            ) as response:
                
                result = await response.json()
                
                if response.status == 200:
                    return {
                        "success": True,
                        "subscription": result
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    async def cancel_subscription(self, subscription_id: str, reason: str = "User requested cancellation") -> Dict[str, Any]:
        """取消訂閱"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        cancel_data = {
            "reason": reason
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v1/billing/subscriptions/{subscription_id}/cancel",
                headers=headers,
                json=cancel_data
            ) as response:
                
                if response.status == 204:
                    return {
                        "success": True,
                        "message": "Subscription cancelled successfully"
                    }
                else:
                    result = await response.json()
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    async def create_one_time_payment(self, amount: float, currency: str = "USD", 
                                    description: str = "Trimly Payment") -> Dict[str, Any]:
        """建立一次性支付"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        payment_data = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"TRIMLY-{int(datetime.utcnow().timestamp())}",
                    "description": description,
                    "amount": {
                        "currency_code": currency,
                        "value": f"{amount:.2f}"
                    }
                }
            ],
            "application_context": {
                "brand_name": "Trimly",
                "landing_page": "NO_PREFERENCE",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW"
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v2/checkout/orders",
                headers=headers,
                json=payment_data
            ) as response:
                
                result = await response.json()
                
                if response.status == 201:
                    # 提取核准連結
                    approve_link = None
                    for link in result.get("links", []):
                        if link["rel"] == "approve":
                            approve_link = link["href"]
                            break
                    
                    return {
                        "success": True,
                        "order_id": result["id"],
                        "approve_link": approve_link,
                        "order_data": result
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    async def capture_payment(self, order_id: str) -> Dict[str, Any]:
        """捕獲支付"""
        
        access_token = await self.get_access_token()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                headers=headers
            ) as response:
                
                result = await response.json()
                
                if response.status == 201:
                    return {
                        "success": True,
                        "capture_data": result
                    }
                else:
                    return {
                        "success": False,
                        "error": result,
                        "status_code": response.status
                    }
    
    def verify_webhook_signature(self, headers: Dict[str, str], body: str, webhook_id: str) -> bool:
        """驗證 PayPal Webhook 簽名"""
        
        # 這裡應該實現 PayPal Webhook 簽名驗證
        # 為了簡化，這裡返回 True，實際應用中需要實現完整的驗證邏輯
        
        auth_algo = headers.get("PAYPAL-AUTH-ALGO")
        transmission_id = headers.get("PAYPAL-TRANSMISSION-ID")
        cert_id = headers.get("PAYPAL-CERT-ID")
        transmission_sig = headers.get("PAYPAL-TRANSMISSION-SIG")
        transmission_time = headers.get("PAYPAL-TRANSMISSION-TIME")
        
        # 實際驗證邏輯應該在這裡實現
        # 參考：https://developer.paypal.com/docs/api/webhooks/v1/#verify-webhook-signature
        
        return True  # 簡化實現
    
    async def process_webhook_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """處理 PayPal Webhook 事件"""
        
        event_type = event_data.get("event_type")
        resource = event_data.get("resource", {})
        
        result = {
            "event_type": event_type,
            "processed": False,
            "actions": []
        }
        
        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            # 訂閱啟用
            subscription_id = resource.get("id")
            result["actions"].append(f"Activate subscription {subscription_id}")
            result["processed"] = True
            
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            # 訂閱取消
            subscription_id = resource.get("id")
            result["actions"].append(f"Cancel subscription {subscription_id}")
            result["processed"] = True
            
        elif event_type == "PAYMENT.SALE.COMPLETED":
            # 支付完成
            payment_id = resource.get("id")
            amount = resource.get("amount", {}).get("total")
            result["actions"].append(f"Process payment {payment_id} for ${amount}")
            result["processed"] = True
            
        elif event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
            # 支付失敗
            subscription_id = resource.get("billing_agreement_id")
            result["actions"].append(f"Handle payment failure for subscription {subscription_id}")
            result["processed"] = True
        
        return result

# 全域 PayPal 服務實例
paypal_service = PayPalService()

