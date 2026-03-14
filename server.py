from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import time
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import cloudinary
import cloudinary.utils
import cloudinary.uploader
import jwt
import hashlib
import httpx
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB
mongo_url = os.environ['MONGO_URL']
db_name = os.environ['DB_NAME']
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# Cloudinary
cloudinary.config(
    cloud_name=os.environ['CLOUDINARY_CLOUD_NAME'],
    api_key=os.environ['CLOUDINARY_API_KEY'],
    api_secret=os.environ['CLOUDINARY_API_SECRET'],
    secure=True
)

JWT_SECRET = os.environ['JWT_SECRET']
OTP_CODE = os.environ.get('OTP_CODE', '123456')

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Models ──
class SendOTPRequest(BaseModel):
    email: str

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str
    name: Optional[str] = None

class AddFriendRequest(BaseModel):
    friend_email: str

class AcceptFriendRequest(BaseModel):
    request_id: str

class SendPhotoRequest(BaseModel):
    receiver_id: str
    image_url: str

class ReactPhotoRequest(BaseModel):
    photo_id: str
    reaction_type: str

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    profile_photo: Optional[str] = None

class RegisterDeviceRequest(BaseModel):
    push_token: str
    device_type: str = "unknown"

class GoogleLoginRequest(BaseModel):
    id_token: str

# ── Auth Helper ──
def create_token(user_id: str, email: str):
    return jwt.encode({"user_id": user_id, "email": email}, JWT_SECRET, algorithm="HS256")

async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Missing or invalid authorization header")
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            logger.warning(f"User not found for ID: {payload.get('user_id')}")
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError as e:
        logger.warning(f"JWT Decode error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

# ── Auth Routes ──
@api_router.post("/send-otp")
@api_router.post("/auth/send-otp") # Alias
async def send_otp(req: SendOTPRequest):
    logger.info(f"OTP requested for {req.email} - Code: {OTP_CODE}")
    return {"message": f"Verification code sent to {req.email}", "email": req.email}

@api_router.post("/verify-otp")
@api_router.post("/auth/email-login") # Alias
async def verify_otp(req: VerifyOTPRequest):
    if req.otp != OTP_CODE:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user:
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "name": req.name or req.email.split("@")[0],
            "email": req.email,
            "profilePhoto": "",
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(user)
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
    
    token = create_token(user["id"], user["email"])
    return {"token": token, "user": user}

# ── Google Auth Route ──
@api_router.post("/auth/google")
@app.post("/auth/google")
async def google_login(req: GoogleLoginRequest):
    try:
        # In a real production app, you'd pass CLIENT_ID to verify_oauth2_token
        # For beta, we use google_requests.Request() and check the payload
        idinfo = id_token.verify_oauth2_token(req.id_token, google_requests.Request())
        
        email = idinfo.get("email")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")
        
        if not email:
            raise HTTPException(status_code=400, detail="No email from Google")
    except ValueError as e:
        logger.error(f"Google Token Verification Error: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")

    # Find or create user
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "name": name or email.split("@")[0],
            "email": email,
            "profilePhoto": picture,
            "createdAt": datetime.now(timezone.utc).isoformat()
        }
        await db.users.insert_one(user)
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
    else:
        # Update profile photo from Google if not set
        if not user.get("profilePhoto") and picture:
            await db.users.update_one({"email": email}, {"$set": {"profilePhoto": picture}})
            user = await db.users.find_one({"email": email}, {"_id": 0})

    token = create_token(user["id"], user["email"])
    return {"token": token, "user": user}
@api_router.get("/profile")
async def get_profile(user=Depends(get_current_user)):
    return {"user": user}

@api_router.put("/profile/update") # Beta requirement path
@api_router.put("/profile")
async def update_profile(req: UpdateProfileRequest, user=Depends(get_current_user)):
    updates = {}
    if req.name:
        updates["name"] = req.name
    if req.profile_photo:
        updates["profilePhoto"] = req.profile_photo
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
    updated = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    return {"user": updated}

# ── Friend Routes ──
@api_router.post("/friends/add") # Beta requirement path
@api_router.post("/add-friend")
async def add_friend(req: AddFriendRequest, user=Depends(get_current_user)):
    if req.friend_email == user["email"]:
        raise HTTPException(status_code=400, detail="Cannot add yourself")
    
    friend = await db.users.find_one({"email": req.friend_email}, {"_id": 0})
    if not friend:
        raise HTTPException(status_code=404, detail="User not found with that email")
    
    # Check friend count
    friend_count = await db.friends.count_documents({
        "$or": [{"userId": user["id"]}, {"friendId": user["id"]}],
        "status": "accepted"
    })
    if friend_count >= 20:
        raise HTTPException(status_code=400, detail="Max 20 friends reached")
    
    existing = await db.friends.find_one({
        "$or": [
            {"userId": user["id"], "friendId": friend["id"]},
            {"userId": friend["id"], "friendId": user["id"]}
        ]
    })
    if existing:
        raise HTTPException(status_code=400, detail="Friend request already exists")
    
    request_id = str(uuid.uuid4())
    await db.friends.insert_one({
        "id": request_id,
        "userId": user["id"],
        "friendId": friend["id"],
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat()
    })
    return {"message": "Friend request sent", "requestId": request_id}

@api_router.post("/accept-friend")
async def accept_friend(req: AcceptFriendRequest, user=Depends(get_current_user)):
    request = await db.friends.find_one({"id": req.request_id, "friendId": user["id"], "status": "pending"})
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    await db.friends.update_one({"id": req.request_id}, {"$set": {"status": "accepted"}})
    return {"message": "Friend request accepted"}

@api_router.post("/reject-friend")
async def reject_friend(req: AcceptFriendRequest, user=Depends(get_current_user)):
    request = await db.friends.find_one({"id": req.request_id, "friendId": user["id"], "status": "pending"})
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    await db.friends.delete_one({"id": req.request_id})
    return {"message": "Friend request rejected"}

@api_router.get("/friends")
async def get_friends(user=Depends(get_current_user)):
    friend_records = await db.friends.find(
        {"$or": [{"userId": user["id"]}, {"friendId": user["id"]}], "status": "accepted"},
        {"_id": 0}
    ).to_list(100)
    
    friends = []
    for rec in friend_records:
        fid = rec["friendId"] if rec["userId"] == user["id"] else rec["userId"]
        f = await db.users.find_one({"id": fid}, {"_id": 0})
        if f:
            friends.append(f)
    return {"friends": friends}

@api_router.get("/friend-requests")
async def get_friend_requests(user=Depends(get_current_user)):
    requests = await db.friends.find(
        {"friendId": user["id"], "status": "pending"}, {"_id": 0}
    ).to_list(100)
    
    enriched = []
    for req in requests:
        sender = await db.users.find_one({"id": req["userId"]}, {"_id": 0})
        if sender:
            enriched.append({**req, "senderName": sender["name"], "senderEmail": sender["email"]})
    return {"requests": enriched}

# ── Cloudinary Routes ──
@api_router.get("/cloudinary/signature")
async def cloudinary_signature(user=Depends(get_current_user)):
    timestamp = int(time.time())
    folder = f"photos/{user['id']}"
    params = {"timestamp": timestamp, "folder": folder}
    signature = cloudinary.utils.api_sign_request(params, os.environ['CLOUDINARY_API_SECRET'])
    return {
        "signature": signature,
        "timestamp": timestamp,
        "cloud_name": os.environ['CLOUDINARY_CLOUD_NAME'],
        "api_key": os.environ['CLOUDINARY_API_KEY'],
        "folder": folder
    }

# ── Photo Routes ──
@api_router.post("/photo/upload") # Beta requirement path
@api_router.post("/send-photo")
async def send_photo(req: SendPhotoRequest, user=Depends(get_current_user)):
    # Verify friendship
    friendship = await db.friends.find_one({
        "$or": [
            {"userId": user["id"], "friendId": req.receiver_id},
            {"userId": req.receiver_id, "friendId": user["id"]}
        ],
        "status": "accepted"
    })
    if not friendship:
        raise HTTPException(status_code=403, detail="Not friends with this user")
    
    photo_id = str(uuid.uuid4())
    photo = {
        "id": photo_id,
        "senderId": user["id"],
        "receiverId": req.receiver_id,
        "imageUrl": req.image_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reactions": []
    }
    await db.photos.insert_one(photo)
    
    # Send push notification
    try:
        devices = await db.devices.find({"userId": req.receiver_id}, {"_id": 0}).to_list(10)
        for device in devices:
            logger.info(f"Push notification to {device['pushToken']}: {user['name']} sent you a moment")
    except Exception as e:
        logger.error(f"Push notification error: {e}")
    
    return {"message": "Photo sent", "photoId": photo_id}

@api_router.get("/inbox")
async def get_inbox(user=Depends(get_current_user)):
    photos = await db.photos.find(
        {"receiverId": user["id"]}, {"_id": 0}
    ).sort("timestamp", -1).to_list(50)
    
    enriched = []
    for p in photos:
        sender = await db.users.find_one({"id": p["senderId"]}, {"_id": 0})
        reactions = await db.photo_reactions.find({"photoId": p["id"]}, {"_id": 0}).to_list(100)
        enriched.append({
            **p,
            "senderName": sender["name"] if sender else "Unknown",
            "senderPhoto": sender.get("profilePhoto", "") if sender else "",
            "reactions": reactions
        })
    return {"photos": enriched}

@api_router.get("/sent-photos")
async def get_sent_photos(user=Depends(get_current_user)):
    photos = await db.photos.find(
        {"senderId": user["id"]}, {"_id": 0}
    ).sort("timestamp", -1).to_list(50)
    
    enriched = []
    for p in photos:
        receiver = await db.users.find_one({"id": p["receiverId"]}, {"_id": 0})
        reactions = await db.photo_reactions.find({"photoId": p["id"]}, {"_id": 0}).to_list(100)
        enriched.append({
            **p,
            "receiverName": receiver["name"] if receiver else "Unknown",
            "reactions": reactions
        })
    return {"photos": enriched}

# ── Reaction Routes ──
@api_router.post("/react-photo")
async def react_photo(req: ReactPhotoRequest, user=Depends(get_current_user)):
    photo = await db.photos.find_one({"id": req.photo_id})
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    
    allowed = ["❤️", "😂", "🔥", "😮"]
    if req.reaction_type not in allowed:
        raise HTTPException(status_code=400, detail="Invalid reaction type")
    
    # Remove existing reaction from this user on this photo
    await db.photo_reactions.delete_many({"photoId": req.photo_id, "userId": user["id"]})
    
    reaction_id = str(uuid.uuid4())
    await db.photo_reactions.insert_one({
        "id": reaction_id,
        "photoId": req.photo_id,
        "userId": user["id"],
        "reactionType": req.reaction_type,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    # Notify photo sender
    sender_id = photo["senderId"]
    if sender_id != user["id"]:
        logger.info(f"Reaction notification: {user['name']} reacted {req.reaction_type} to photo")
    
    return {"message": "Reaction added", "reactionId": reaction_id}

# ── Widget Route ──
@api_router.get("/widget/latest-photo")
async def widget_latest_photo(user_id: str):
    photo = await db.photos.find_one(
        {"receiverId": user_id}, {"_id": 0}
    )
    if not photo:
        # Try sorting
        photo = await db.photos.find(
            {"receiverId": user_id}, {"_id": 0}
        ).sort("timestamp", -1).to_list(1)
        if photo:
            photo = photo[0]
        else:
            return {"image_url": None, "sender_name": None, "timestamp": None}
    else:
        photos = await db.photos.find(
            {"receiverId": user_id}, {"_id": 0}
        ).sort("timestamp", -1).to_list(1)
        photo = photos[0] if photos else photo
    
    sender = await db.users.find_one({"id": photo["senderId"]}, {"_id": 0})
    return {
        "image_url": photo["imageUrl"],
        "sender_name": sender["name"] if sender else "Unknown",
        "timestamp": photo["timestamp"]
    }

# ── Device Routes ──
@api_router.post("/register-device")
async def register_device(req: RegisterDeviceRequest, user=Depends(get_current_user)):
    existing = await db.devices.find_one({"userId": user["id"], "pushToken": req.push_token})
    if not existing:
        await db.devices.insert_one({
            "id": str(uuid.uuid4()),
            "userId": user["id"],
            "pushToken": req.push_token,
            "deviceType": req.device_type
        })
    return {"message": "Device registered"}

# ── Search Users ──
@api_router.get("/friends/search") # Beta requirement path
@api_router.get("/search-users")
async def search_users(q: str, user=Depends(get_current_user)):
    if len(q) < 2:
        return {"users": []}
    users = await db.users.find(
        {"email": {"$regex": q, "$options": "i"}, "id": {"$ne": user["id"]}},
        {"_id": 0}
    ).to_list(10)
    return {"users": users}

# ── Health ──
@app.get("/health") # Also available at root
@api_router.get("/health")
async def health():
    return {"status": "healthy", "service": "pocketcircle"}

@app.get("/auth/google")
async def google_redirect_check():
    return {"status": "ready", "message": "Google OAuth endpoint is active. Use POST to process sessions."}

@app.exception_handler(404)
async def custom_404_handler(request, __):
    logger.warning(f"404 Not Found: {request.url.path}")
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Not Found",
            "message": f"Path {request.url.path} not found on PocketCircle server",
            "path": request.url.path
        }
    )

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
