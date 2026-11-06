def valid(boxes, W, L, a, b):
    """Boxes inside pallet, correct size, no overlaps."""
    for x in boxes:
        if x["a"] < 0 or x["b"] < 0 or x["c"] > W or x["d"] > L:
            return False, f"out of bounds {x}"
        if sorted((x["c"] - x["a"], x["d"] - x["b"])) != sorted((a, b)):
            return False, f"bad size {x}"
    for i, p in enumerate(boxes):
        for q in boxes[i + 1:]:
            if p["a"] < q["c"] and q["a"] < p["c"] and p["b"] < q["d"] and q["b"] < p["d"]:
                return False, f"overlap {p} {q}"
    return True, ""
