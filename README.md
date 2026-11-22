# FreshKart - Online Grocery Application

FreshKart is a working online grocery web app: customers search products, build a cart, place an order, pay, and follow the delivery status. The project was built using Scrum, with user stories, sprints, a task board, a Definition of Done, test cases and a GitHub history.

> **Simulated parts:** the payment gateway and the delivery tracking (status changes and rider movement) are simulations. No real money, GPS or notification service is used, and the pages say so on screen.

## Features

- Product catalogue with search and category filter, with in-stock, low-stock and out-of-stock labels
- Shopping cart with quantity rules and automatic price calculation
- Checkout with validation (name, mobile number, address)
- Simulated payment by UPI or card, with failure handling and retry
- Order summary and order history
- Simulated delivery tracking: status bar, route view with a moving rider, estimated time and a timeline with timestamps
- Store staff page to move orders through Placed, Packed, Out for Delivery and Delivered

## Tech stack

- Python 3 and Flask
- SQLite database
- HTML templates (Jinja) and CSS

## Run it

```
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

The database file `grocery.db` is created and filled with 30 products on the first run. To reset all data, stop the app, delete `grocery.db` and start it again.

## Demo walkthrough

1. **Shop:** search "milk" or filter by category.
2. **Cart:** add items and see subtotal, delivery fee and total. Try adding more than the available stock.
3. **Checkout:** enter delivery details (10-digit mobile number, full address).
4. **Payment (simulated):** a card ending `0002` is declined, `9995` is insufficient funds, `0069` is blocked. Any other 16-digit card with a future expiry and a 3-digit CVV succeeds. For UPI, an ID starting with `fail` is declined and any other valid `name@bank` succeeds.
5. **Tracking (simulated):** open "Store Staff (demo)", move the order forward, and watch the order page update.

## Business rules

- Maximum 10 units of one item per order; quantity must be a whole number of at least 1 and cannot exceed stock.
- Delivery fee is Rs 30, free for orders of Rs 300 or more.
- Stock is reduced only when payment succeeds, using a single atomic SQL update inside a transaction. If the last unit is bought by someone else first, the order is cancelled and the customer is not charged.
- Delivery status moves only forward: Placed, Packed, Out for Delivery, Delivered. Unpaid orders cannot ship.

## Tests

```
python run_tests.py
```

Runs the automated test cases (positive, negative and boundary) with expected vs actual results and writes `TEST_REPORT.md`. They cover search, cart limits, price calculation, checkout validation, payment success, failure and retry, stock running out during payment, and the delivery status flow.

## Project structure

| Path | Purpose |
|---|---|
| `app.py` | Routes, validation rules, simulated payment gateway, database setup |
| `templates/` | HTML pages |
| `static/style.css` | Styling |
| `run_tests.py` | Automated test cases |
| `TEST_REPORT.md` | Latest test results |

## Database

- `products` - catalogue and stock
- `orders` - customer details, totals, status and payment status
- `order_items` - items in each order
- `payment_attempts` - every payment attempt and its outcome
- `order_events` - time of each delivery status change

## Team

| Name | Roll No. | Area |
|---|---|---|
| Vaishnavi Ramesh | 57 | Catalogue and search |
| Shraddha Gotawale | 45 | Cart |
| Kritika Karnani | 27 | Checkout and payment |
| Rigved Shelar | 38 | Tracking and tests |

## Limitations

User login and accounts, real payments, real GPS, and email or SMS notifications are not implemented.admin_*`, `run_tests.py`)
