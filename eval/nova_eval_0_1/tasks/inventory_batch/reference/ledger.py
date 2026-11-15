class InventoryLedger:
    """
    Manages inventory stock levels.
    Adjustments are staged first, then committed via commit_batch().
    Contract: Committing applies all staged adjustments exactly once.
    """

    def __init__(self):
        self._stock = {}
        self._staged = []

    def stage_adjustment(self, sku, quantity):
        self._staged.append({"sku": sku, "quantity": quantity})

    def commit_batch(self):
        for adj in self._staged:
            self._stock[adj["sku"]] = (
                self._stock.get(adj["sku"], 0) + adj["quantity"]
            )

        self._staged.clear()
        return self._stock

    def get_stock(self, sku):
        return self._stock.get(sku, 0)
