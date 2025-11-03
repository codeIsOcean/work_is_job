#!/usr/bin/env python3
"""
Скрипт для автоматической настройки GitHub Secrets для CI/CD
"""
import os
import sys
import requests
import base64
from nacl import encoding, public
import json

# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"

def get_public_key(repo_owner, repo_name, token):
    """Получает публичный ключ репозитория для шифрования secrets"""
    url = f"{GITHUB_API_BASE}/repos/{repo_owner}/{repo_name}/actions/secrets/public-key"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"❌ Ошибка получения публичного ключа: {response.status_code}")
        print(f"   Ответ: {response.text}")
        return None
    
    return response.json()

def encrypt_secret(public_key: str, secret_value: str) -> str:
    """Шифрует secret используя публичный ключ репозитория"""
    public_key_obj = public.PublicKey(
        public_key.encode("utf-8"), 
        encoding.Base64Encoder()
    )
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def create_or_update_secret(repo_owner, repo_name, secret_name, secret_value, encrypted_value, public_key_id, token):
    """Создает или обновляет secret в GitHub"""
    url = f"{GITHUB_API_BASE}/repos/{repo_owner}/{repo_name}/actions/secrets/{secret_name}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }
    data = {
        "encrypted_value": encrypted_value,
        "key_id": public_key_id
    }
    
    response = requests.put(url, headers=headers, json=data)
    if response.status_code in [201, 204]:
        print(f"✅ Secret '{secret_name}' успешно создан/обновлен")
        return True
    else:
        print(f"❌ Ошибка создания secret '{secret_name}': {response.status_code}")
        print(f"   Ответ: {response.text}")
        return False

def main():
    print("🔧 Настройка GitHub Secrets для CI/CD\n")
    
    # Получаем токен GitHub
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("❌ GITHUB_TOKEN не установлен!")
        print("\n📋 Инструкция:")
        print("1. Создай Personal Access Token в GitHub:")
        print("   Settings → Developer settings → Personal access tokens → Tokens (classic)")
        print("   Создай токен с правами: repo (полный доступ)")
        print("2. Установи токен в переменную окружения:")
        print("   export GITHUB_TOKEN='your_token_here'")
        print("   или на Windows:")
        print("   set GITHUB_TOKEN=your_token_here")
        sys.exit(1)
    
    # Получаем информацию о репозитории
    repo_owner = input("Введите владельца репозитория (username или organization): ").strip()
    repo_name = input("Введите название репозитория: ").strip()
    
    if not repo_owner or not repo_name:
        print("❌ Необходимо указать владельца и название репозитория!")
        sys.exit(1)
    
    print(f"\n📋 Настройка secrets для репозитория: {repo_owner}/{repo_name}\n")
    
    # Получаем публичный ключ
    print("🔑 Получение публичного ключа репозитория...")
    key_data = get_public_key(repo_owner, repo_name, token)
    if not key_data:
        sys.exit(1)
    
    public_key = key_data["key"]
    key_id = key_data["key_id"]
    print(f"✅ Публичный ключ получен (key_id: {key_id})\n")
    
    # Secrets для добавления
    secrets = {
        "TEST_SERVER_HOST": "88.210.35.183",
        "TEST_SERVER_USER": "root",
        "TEST_SERVER_SSH_KEY": None  # Получим с сервера
    }
    
    # Получаем SSH ключ с сервера
    print("🔑 Получение SSH ключа с сервера...")
    import subprocess
    try:
        ssh_key_result = subprocess.run(
            ["ssh", "root@88.210.35.183", "cat ~/.ssh/github_actions_deploy"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if ssh_key_result.returncode == 0:
            secrets["TEST_SERVER_SSH_KEY"] = ssh_key_result.stdout.strip()
            print("✅ SSH ключ получен с сервера\n")
        else:
            print("⚠️  Не удалось получить SSH ключ с сервера")
            print("   Введите SSH приватный ключ вручную:")
            secrets["TEST_SERVER_SSH_KEY"] = input("SSH приватный ключ: ").strip()
    except Exception as e:
        print(f"⚠️  Ошибка получения SSH ключа: {e}")
        print("   Введите SSH приватный ключ вручную:")
        secrets["TEST_SERVER_SSH_KEY"] = input("SSH приватный ключ: ").strip()
    
    # Добавляем secrets
    print("\n📝 Добавление secrets в GitHub...\n")
    success_count = 0
    
    for secret_name, secret_value in secrets.items():
        if not secret_value:
            print(f"⚠️  Secret '{secret_name}' пропущен (значение не установлено)")
            continue
        
        print(f"🔐 Шифрование и добавление '{secret_name}'...")
        encrypted_value = encrypt_secret(public_key, secret_value)
        
        if create_or_update_secret(repo_owner, repo_name, secret_name, secret_value, encrypted_value, key_id, token):
            success_count += 1
    
    print(f"\n✅ Готово! Добавлено {success_count} из {len(secrets)} secrets")
    print("\n🎉 Теперь можно использовать CI/CD!")
    print("   Сделай push в ветку 'test' чтобы проверить деплой")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

