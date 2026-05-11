"""Управление инвентарем пользователя."""

import os
import time
from typing import Any, Dict, List
import requests
from config import (
    BASE_URL,
    REQUEST_TIMEOUT,
    DEFAULT_DELAY,
    OUTPUT_DIR,
    INVENTORY_FILE,
    PARSED_INVENTORY_FILE
)
from utils import load_json, save_json

# Разрешённые ранги — единое место определения для всего проекта
# Порядок рангов: B > C > D > E (от высшего к низшему)
ALLOWED_RANKS = {"E", "D", "C", "B"}


class InventoryManager:
    """Менеджер для работы с инвентарем."""

    def __init__(self, output_dir: str = OUTPUT_DIR):
        self.output_dir = output_dir
        self.inventory_path = os.path.join(output_dir, INVENTORY_FILE)
        self.parsed_inventory_path = os.path.join(output_dir, PARSED_INVENTORY_FILE)

    def load_inventory(self) -> List[Dict[str, Any]]:
        return load_json(self.inventory_path, default=[])

    def save_inventory(self, inventory: List[Dict[str, Any]]) -> bool:
        return save_json(self.inventory_path, inventory)

    def load_parsed_inventory(self) -> Dict[str, Dict[str, Any]]:
        return load_json(self.parsed_inventory_path, default={})

    def save_parsed_inventory(
        self,
        parsed_inventory: Dict[str, Dict[str, Any]]
    ) -> bool:
        return save_json(self.parsed_inventory_path, parsed_inventory)

    def remove_card(self, card: Dict[str, Any]) -> bool:
        inventory = self.load_inventory()
        try:
            inventory.remove(card)
            return self.save_inventory(inventory)
        except ValueError:
            return False

    def sync_inventories(self) -> bool:
        """
        Синхронизирует обычный и пропарсенный инвентарь при запуске.

        1. Удаляет из inventory.json карты которые уже есть в parsed_inventory.json
        2. Удаляет из parsed_inventory.json карты которых нет в новом inventory.json
        3. Удаляет из parsed_inventory.json карты с недопустимыми рангами (не B/C/D/E)
        """
        inventory = self.load_inventory()
        parsed_inventory = self.load_parsed_inventory()

        if not inventory:
            print("   Инвентарь пуст")
            return True

        if not parsed_inventory:
            print("   Пропарсенный инвентарь пуст")
            return True

        inventory_instance_ids = set()
        for card in inventory:
            instance_id = card.get('id')
            if instance_id:
                inventory_instance_ids.add(str(instance_id))

        parsed_instance_ids = set()
        for card_id_str, card_data in list(parsed_inventory.items()):
            instance_id = card_data.get('instance_id')
            if instance_id:
                parsed_instance_ids.add(str(instance_id))

        # 1. Удаляем из inventory.json карты которые есть в parsed_inventory.json
        initial_inventory_count = len(inventory)
        inventory = [
            card for card in inventory
            if str(card.get('id', '')) not in parsed_instance_ids
        ]
        removed_from_inventory = initial_inventory_count - len(inventory)

        # 2. Удаляем из parsed_inventory.json карты которых нет в inventory.json
        initial_parsed_count = len(parsed_inventory)
        parsed_inventory = {
            card_id_str: card_data
            for card_id_str, card_data in parsed_inventory.items()
            if str(card_data.get('instance_id', '')) in inventory_instance_ids
        }
        removed_from_parsed = initial_parsed_count - len(parsed_inventory)

        # 3. Удаляем из parsed_inventory карты с недопустимыми рангами (не B/C/D/E)
        before_rank_filter = len(parsed_inventory)
        parsed_inventory = {
            card_id_str: card_data
            for card_id_str, card_data in parsed_inventory.items()
            if str(card_data.get('rank', '')).upper() in ALLOWED_RANKS
        }
        removed_wrong_rank = before_rank_filter - len(parsed_inventory)
        if removed_wrong_rank > 0:
            print(f"   🗑️  Удалено из parsed (недопустимый ранг): {removed_wrong_rank}")

        save_success = True

        if removed_from_inventory > 0:
            print(f"   Удалено из inventory: {removed_from_inventory}")
            if not self.save_inventory(inventory):
                save_success = False
                print("   ⚠️  Ошибка сохранения inventory")

        if removed_from_parsed > 0 or removed_wrong_rank > 0:
            print(f"   Удалено из parsed (нет в инвентаре): {removed_from_parsed}")
            if not self.save_parsed_inventory(parsed_inventory):
                save_success = False
                print("   ⚠️  Ошибка сохранения parsed_inventory")

        return save_success


def fetch_user_cards(
    session: requests.Session,
    user_id: str,
    offset: int = 0
) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/trades/{user_id}/availableCardsLoad"

    headers = {
        "Referer": f"{BASE_URL}/trades/{user_id}",
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    try:
        response = session.post(
            url,
            headers=headers,
            data={"offset": offset},
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return []

        data = response.json()
        return data.get("cards", [])

    except (requests.RequestException, ValueError):
        return []


def get_user_inventory(
    session: requests.Session,
    user_id: str,
    page_size: int = 60
) -> List[Dict[str, Any]]:
    all_cards = []
    offset = 0

    while True:
        cards = fetch_user_cards(session, user_id, offset)

        if not cards:
            break

        all_cards.extend(cards)
        offset += len(cards)

        if len(cards) < page_size:
            break

        time.sleep(DEFAULT_DELAY)

    return all_cards