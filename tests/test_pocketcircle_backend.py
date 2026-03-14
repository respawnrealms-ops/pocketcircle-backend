import pytest
import requests
import os
import time

# Authentication and OTP endpoints
# User profile endpoints
# Friend management endpoints (add, accept, reject, list, requests)
# Photo endpoints (send, inbox, sent)
# Reaction endpoints
# Widget endpoint
# Cloudinary signature endpoint

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://friend-feed-11.preview.emergentagent.com').rstrip('/')

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def test_user_token(api_client):
    """Get token for test@example.com using OTP 123456"""
    # Send OTP
    otp_res = api_client.post(f"{BASE_URL}/api/send-otp", json={"email": "test@example.com"})
    assert otp_res.status_code == 200
    
    # Verify OTP
    verify_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
        "email": "test@example.com",
        "otp": "123456"
    })
    assert verify_res.status_code == 200
    data = verify_res.json()
    return data['token']

@pytest.fixture
def bob_user_token(api_client):
    """Get token for bob@example.com using OTP 123456"""
    # Send OTP
    otp_res = api_client.post(f"{BASE_URL}/api/send-otp", json={"email": "bob@example.com"})
    assert otp_res.status_code == 200
    
    # Verify OTP
    verify_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
        "email": "bob@example.com",
        "otp": "123456"
    })
    assert verify_res.status_code == 200
    data = verify_res.json()
    return data['token']

class TestHealth:
    """Health check endpoint"""
    
    def test_health_check(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert data['service'] == 'pocketcircle'

class TestAuth:
    """Authentication endpoint tests"""
    
    def test_send_otp_success(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/send-otp", json={
            "email": "test@example.com"
        })
        assert response.status_code == 200
        data = response.json()
        assert 'message' in data
        assert data['email'] == 'test@example.com'
    
    def test_verify_otp_success_existing_user(self, api_client):
        # First send OTP
        api_client.post(f"{BASE_URL}/api/send-otp", json={"email": "test@example.com"})
        
        # Verify with correct OTP (123456)
        response = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": "test@example.com",
            "otp": "123456"
        })
        assert response.status_code == 200
        data = response.json()
        assert 'token' in data
        assert 'user' in data
        assert data['user']['email'] == 'test@example.com'
        assert 'id' in data['user']
        assert 'name' in data['user']
    
    def test_verify_otp_new_user_creation(self, api_client):
        # Use unique email for new user
        new_email = f"TEST_newuser_{int(time.time())}@example.com"
        
        # Send OTP
        api_client.post(f"{BASE_URL}/api/send-otp", json={"email": new_email})
        
        # Verify OTP - should create new user
        response = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": new_email,
            "otp": "123456",
            "name": "Test New User"
        })
        assert response.status_code == 200
        data = response.json()
        assert 'token' in data
        assert 'user' in data
        assert data['user']['email'] == new_email
        assert data['user']['name'] == 'Test New User'
        
        # Verify user persists by getting profile
        profile_res = api_client.get(f"{BASE_URL}/api/profile", headers={
            'Authorization': f"Bearer {data['token']}"
        })
        assert profile_res.status_code == 200
        profile_data = profile_res.json()
        assert profile_data['user']['email'] == new_email
    
    def test_verify_otp_wrong_code(self, api_client):
        # Send OTP
        api_client.post(f"{BASE_URL}/api/send-otp", json={"email": "test@example.com"})
        
        # Verify with wrong OTP
        response = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": "test@example.com",
            "otp": "999999"
        })
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'Invalid OTP' in data['detail']

class TestProfile:
    """Profile endpoint tests"""
    
    def test_get_profile_success(self, api_client, test_user_token):
        response = api_client.get(f"{BASE_URL}/api/profile", headers={
            'Authorization': f'Bearer {test_user_token}'
        })
        assert response.status_code == 200
        data = response.json()
        assert 'user' in data
        assert 'id' in data['user']
        assert 'email' in data['user']
        assert data['user']['email'] == 'test@example.com'
    
    def test_get_profile_no_auth(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/profile")
        assert response.status_code == 401
    
    def test_get_profile_invalid_token(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/profile", headers={
            'Authorization': 'Bearer invalid_token_12345'
        })
        assert response.status_code == 401
    
    def test_update_profile_name(self, api_client, test_user_token):
        """Test updating profile name"""
        response = api_client.put(f"{BASE_URL}/api/profile", 
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={"name": "TEST_Updated_Name"}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'user' in data
        assert data['user']['name'] == 'TEST_Updated_Name'
        
        # Verify persistence with GET
        get_res = api_client.get(f"{BASE_URL}/api/profile", 
            headers={'Authorization': f'Bearer {test_user_token}'}
        )
        assert get_res.status_code == 200
        assert get_res.json()['user']['name'] == 'TEST_Updated_Name'
    
    def test_update_profile_photo(self, api_client, test_user_token):
        """Test updating profile photo URL"""
        test_photo_url = "https://res.cloudinary.com/test/image/upload/v123/test.jpg"
        response = api_client.put(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={"profile_photo": test_photo_url}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'user' in data
        assert data['user']['profilePhoto'] == test_photo_url
        
        # Verify persistence
        get_res = api_client.get(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {test_user_token}'}
        )
        assert get_res.status_code == 200
        assert get_res.json()['user']['profilePhoto'] == test_photo_url
    
    def test_update_profile_name_and_photo(self, api_client, test_user_token):
        """Test updating both name and photo"""
        response = api_client.put(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "name": "TEST_Full_Update",
                "profile_photo": "https://res.cloudinary.com/test/image/upload/v456/full.jpg"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data['user']['name'] == 'TEST_Full_Update'
        assert data['user']['profilePhoto'] == 'https://res.cloudinary.com/test/image/upload/v456/full.jpg'


class TestFriends:
    """Friend management endpoint tests"""
    
    def test_get_friends_list(self, api_client, test_user_token):
        response = api_client.get(f"{BASE_URL}/api/friends", headers={
            'Authorization': f'Bearer {test_user_token}'
        })
        assert response.status_code == 200
        data = response.json()
        assert 'friends' in data
        assert isinstance(data['friends'], list)
        # test@example.com and bob@example.com are already friends
        assert len(data['friends']) > 0
    
    def test_get_friend_requests_list(self, api_client, test_user_token):
        response = api_client.get(f"{BASE_URL}/api/friend-requests", headers={
            'Authorization': f'Bearer {test_user_token}'
        })
        assert response.status_code == 200
        data = response.json()
        assert 'requests' in data
        assert isinstance(data['requests'], list)
    
    def test_add_friend_success(self, api_client, test_user_token):
        # Create a new user to add as friend
        new_email = f"TEST_friend_{int(time.time())}@example.com"
        api_client.post(f"{BASE_URL}/api/send-otp", json={"email": new_email})
        new_user_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": new_email,
            "otp": "123456"
        })
        assert new_user_res.status_code == 200
        
        # Add friend
        response = api_client.post(f"{BASE_URL}/api/add-friend", 
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={"friend_email": new_email}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'requestId' in data
        assert 'message' in data
    
    def test_add_friend_user_not_found(self, api_client, test_user_token):
        response = api_client.post(f"{BASE_URL}/api/add-friend",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={"friend_email": "nonexistent_12345@example.com"}
        )
        assert response.status_code == 404
        data = response.json()
        assert 'detail' in data
    
    def test_add_friend_cannot_add_self(self, api_client, test_user_token):
        response = api_client.post(f"{BASE_URL}/api/add-friend",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={"friend_email": "test@example.com"}
        )
        assert response.status_code == 400
        data = response.json()
        assert 'Cannot add yourself' in data['detail']
    
    def test_accept_friend_request_flow(self, api_client):
        # Create two new users
        sender_email = f"TEST_sender_{int(time.time())}@example.com"
        receiver_email = f"TEST_receiver_{int(time.time())}@example.com"
        
        # Create sender
        api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": sender_email, "otp": "123456"
        })
        sender_token_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": sender_email, "otp": "123456"
        })
        sender_token = sender_token_res.json()['token']
        
        # Create receiver
        api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": receiver_email, "otp": "123456"
        })
        receiver_token_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": receiver_email, "otp": "123456"
        })
        receiver_token = receiver_token_res.json()['token']
        
        # Sender sends friend request
        add_res = api_client.post(f"{BASE_URL}/api/add-friend",
            headers={'Authorization': f'Bearer {sender_token}'},
            json={"friend_email": receiver_email}
        )
        assert add_res.status_code == 200
        request_id = add_res.json()['requestId']
        
        # Receiver gets pending requests
        requests_res = api_client.get(f"{BASE_URL}/api/friend-requests",
            headers={'Authorization': f'Bearer {receiver_token}'}
        )
        assert requests_res.status_code == 200
        pending = requests_res.json()['requests']
        assert len(pending) > 0
        assert any(r['id'] == request_id for r in pending)
        
        # Receiver accepts request
        accept_res = api_client.post(f"{BASE_URL}/api/accept-friend",
            headers={'Authorization': f'Bearer {receiver_token}'},
            json={"request_id": request_id}
        )
        assert accept_res.status_code == 200
        
        # Verify they are now friends
        friends_res = api_client.get(f"{BASE_URL}/api/friends",
            headers={'Authorization': f'Bearer {receiver_token}'}
        )
        assert friends_res.status_code == 200
        friends = friends_res.json()['friends']
        assert len(friends) > 0
    
    def test_reject_friend_request_flow(self, api_client):
        # Create two new users
        sender_email = f"TEST_sender_reject_{int(time.time())}@example.com"
        receiver_email = f"TEST_receiver_reject_{int(time.time())}@example.com"
        
        # Create sender
        api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": sender_email, "otp": "123456"
        })
        sender_token_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": sender_email, "otp": "123456"
        })
        sender_token = sender_token_res.json()['token']
        
        # Create receiver
        api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": receiver_email, "otp": "123456"
        })
        receiver_token_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": receiver_email, "otp": "123456"
        })
        receiver_token = receiver_token_res.json()['token']
        
        # Sender sends friend request
        add_res = api_client.post(f"{BASE_URL}/api/add-friend",
            headers={'Authorization': f'Bearer {sender_token}'},
            json={"friend_email": receiver_email}
        )
        assert add_res.status_code == 200
        request_id = add_res.json()['requestId']
        
        # Receiver rejects request
        reject_res = api_client.post(f"{BASE_URL}/api/reject-friend",
            headers={'Authorization': f'Bearer {receiver_token}'},
            json={"request_id": request_id}
        )
        assert reject_res.status_code == 200
        
        # Verify request no longer in pending
        requests_res = api_client.get(f"{BASE_URL}/api/friend-requests",
            headers={'Authorization': f'Bearer {receiver_token}'}
        )
        assert requests_res.status_code == 200
        pending = requests_res.json()['requests']
        assert not any(r['id'] == request_id for r in pending)

class TestPhotos:
    """Photo sending and inbox endpoint tests"""
    
    def test_send_photo_success(self, api_client, test_user_token, bob_user_token):
        # Get bob's user ID
        bob_profile = api_client.get(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {bob_user_token}'}
        ).json()['user']
        bob_id = bob_profile['id']
        
        # Send photo from test user to bob
        response = api_client.post(f"{BASE_URL}/api/send-photo",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "receiver_id": bob_id,
                "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert 'photoId' in data
        assert 'message' in data
    
    def test_send_photo_not_friends(self, api_client, test_user_token):
        # Create a new user (not friends with test user)
        new_email = f"TEST_nonfriend_{int(time.time())}@example.com"
        new_user_res = api_client.post(f"{BASE_URL}/api/verify-otp", json={
            "email": new_email,
            "otp": "123456"
        })
        new_user_id = new_user_res.json()['user']['id']
        
        # Try to send photo
        response = api_client.post(f"{BASE_URL}/api/send-photo",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "receiver_id": new_user_id,
                "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg"
            }
        )
        assert response.status_code == 403
        data = response.json()
        assert 'Not friends' in data['detail']
    
    def test_get_inbox(self, api_client, bob_user_token):
        response = api_client.get(f"{BASE_URL}/api/inbox",
            headers={'Authorization': f'Bearer {bob_user_token}'}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'photos' in data
        assert isinstance(data['photos'], list)
        # Bob should have at least one photo from previous test
        if len(data['photos']) > 0:
            photo = data['photos'][0]
            assert 'id' in photo
            assert 'imageUrl' in photo
            assert 'senderName' in photo
            assert 'timestamp' in photo
            assert 'reactions' in photo
    
    def test_get_sent_photos(self, api_client, test_user_token):
        response = api_client.get(f"{BASE_URL}/api/sent-photos",
            headers={'Authorization': f'Bearer {test_user_token}'}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'photos' in data
        assert isinstance(data['photos'], list)

class TestReactions:
    """Photo reaction endpoint tests"""
    
    def test_react_to_photo_success(self, api_client, test_user_token, bob_user_token):
        # First, send a photo from test user to bob
        bob_profile = api_client.get(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {bob_user_token}'}
        ).json()['user']
        bob_id = bob_profile['id']
        
        send_res = api_client.post(f"{BASE_URL}/api/send-photo",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "receiver_id": bob_id,
                "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg"
            }
        )
        photo_id = send_res.json()['photoId']
        
        # Bob reacts to the photo
        response = api_client.post(f"{BASE_URL}/api/react-photo",
            headers={'Authorization': f'Bearer {bob_user_token}'},
            json={
                "photo_id": photo_id,
                "reaction_type": "❤️"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert 'reactionId' in data
        assert 'message' in data
    
    def test_react_invalid_reaction_type(self, api_client, test_user_token, bob_user_token):
        # First, send a photo
        bob_profile = api_client.get(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {bob_user_token}'}
        ).json()['user']
        bob_id = bob_profile['id']
        
        send_res = api_client.post(f"{BASE_URL}/api/send-photo",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "receiver_id": bob_id,
                "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg"
            }
        )
        photo_id = send_res.json()['photoId']
        
        # Try invalid reaction
        response = api_client.post(f"{BASE_URL}/api/react-photo",
            headers={'Authorization': f'Bearer {bob_user_token}'},
            json={
                "photo_id": photo_id,
                "reaction_type": "👍"  # Not in allowed list
            }
        )
        assert response.status_code == 400
        data = response.json()
        assert 'Invalid reaction' in data['detail']
    
    def test_react_photo_not_found(self, api_client, test_user_token):
        response = api_client.post(f"{BASE_URL}/api/react-photo",
            headers={'Authorization': f'Bearer {test_user_token}'},
            json={
                "photo_id": "nonexistent_photo_id_12345",
                "reaction_type": "❤️"
            }
        )
        assert response.status_code == 404

class TestCloudinary:
    """Cloudinary signature endpoint test"""
    
    def test_cloudinary_signature(self, api_client, test_user_token):
        response = api_client.get(f"{BASE_URL}/api/cloudinary/signature",
            headers={'Authorization': f'Bearer {test_user_token}'}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'signature' in data
        assert 'timestamp' in data
        assert 'cloud_name' in data
        assert 'api_key' in data
        assert 'folder' in data
        assert isinstance(data['timestamp'], int)
        assert len(data['signature']) > 0

class TestWidget:
    """Widget endpoint test (public, no auth)"""
    
    def test_widget_latest_photo(self, api_client, bob_user_token):
        # Get bob's user ID
        bob_profile = api_client.get(f"{BASE_URL}/api/profile",
            headers={'Authorization': f'Bearer {bob_user_token}'}
        ).json()['user']
        bob_id = bob_profile['id']
        
        # Widget endpoint is public
        response = api_client.get(f"{BASE_URL}/api/widget/latest-photo", params={
            "user_id": bob_id
        })
        assert response.status_code == 200
        data = response.json()
        # Should have keys even if no photos
        assert 'image_url' in data
        assert 'sender_name' in data
        assert 'timestamp' in data
