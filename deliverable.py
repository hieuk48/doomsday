"""
doomsday-network/doomsday: Steam Vault Exchange Implementation

Implements a vault that allows users to exchange 100,000 DOOM ($wDOOM) tokens
for a $10 Steam Digital Gift Card. There are 10 cards available in the vault.

Constraints:
- Each user can only redeem if there are cards available.
- Each redemption deducts 100,000 DOOM from the user's balance.
- On successful redemption, the user receives a unique Steam Gift Card code.
- No external dependencies are used.

Assumptions:
- There exists a User class with a 'doom_balance' attribute.
- There is a persistent storage for gift card codes and redemptions.
- This code is a module to be integrated into the main doomsday codebase.
"""

from typing import Dict, List, Optional


class User:
    """
    Represents a user in the Doomsday network.
    """
    def __init__(self, user_id: str, doom_balance: int) -> None:
        self.user_id = user_id
        self.doom_balance = doom_balance

    def deduct_doom(self, amount: int) -> bool:
        """
        Deducts DOOM tokens from the user's balance if sufficient.
        Returns True if successful, False otherwise.
        """
        if self.doom_balance >= amount:
            self.doom_balance -= amount
            return True
        return False


class SteamVault:
    """
    Steam Vault for exchanging DOOM tokens for Steam Gift Cards.
    """
    EXCHANGE_AMOUNT: int = 100_000  # 100,000 DOOM
    CARD_VALUE_USD: int = 10        # $10 per card
    VAULT_SIZE: int = 10            # 10 cards available

    def __init__(self, gift_card_codes: List[str]) -> None:
        """
        Initializes the vault with a list of unique Steam Gift Card codes.
        """
        if len(gift_card_codes) != self.VAULT_SIZE:
            raise ValueError(f"Vault must be initialized with {self.VAULT_SIZE} unique codes.")
        self._available_codes: List[str] = gift_card_codes.copy()
        self._redemptions: Dict[str, str] = {}  # user_id -> code

    def available(self) -> int:
        """
        Returns the number of gift cards still available.
        """
        return len(self._available_codes)

    def has_redeemed(self, user: User) -> bool:
        """
        Checks if the user has already redeemed a card.
        """
        return user.user_id in self._redemptions

    def redeem(self, user: User) -> Optional[str]:
        """
        Redeems a Steam Gift Card for the user if possible.
        Deducts DOOM tokens and returns the gift card code if successful.
        Returns None if redemption fails (insufficient balance, already redeemed, or out of stock).
        """
        if self.has_redeemed(user):
            return None  # User already redeemed

        if self.available() == 0:
            return None  # No cards left

        if not user.deduct_doom(self.EXCHANGE_AMOUNT):
            return None  # Insufficient DOOM balance

        code = self._available_codes.pop(0)
        self._redemptions[user.user_id] = code
        return code

    def get_user_code(self, user: User) -> Optional[str]:
        """
        Returns the gift card code redeemed by the user, if any.
        """
        return self._redemptions.get(user.user_id)


# --- Example Usage & Tests ---

def _test_steam_vault() -> None:
    # Prepare 10 unique codes
    codes = [f"STEAM-GIFT-{i:04d}" for i in range(1, 11)]
    vault = SteamVault(codes)

    # Create 11 users, only 10 can redeem
    users = [User(f"user{i}", 100_000) for i in range(1, 12)]

    # All users attempt to redeem
    results = []
    for user in users:
        code = vault.redeem(user)
        results.append((user.user_id, code))

    # Check that only 10 redemptions succeeded
    successful = [r for r in results if r[1] is not None]
    failed = [r for r in results if r[1] is None]
    assert len(successful) == 10, "Exactly 10 redemptions should succeed"
    assert len(failed) == 1, "1 user should fail due to vault depletion"
    assert vault.available() == 0, "Vault should be empty"

    # Test double redemption
    user = users[0]
    code1 = vault.get_user_code(user)
    code2 = vault.redeem(user)
    assert code2 is None, "User cannot redeem twice"
    assert code1 is not None, "User should have a code from first redemption"

    # Test insufficient balance
    poor_user = User("poor_user", 50_000)
    code = vault.redeem(poor_user)
    assert code is None, "Redemption should fail if balance is insufficient"

    print("All SteamVault tests passed.")


if __name__ == "__main__":
    _test_steam_vault()