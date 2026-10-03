# Order totals ignore quantities

Our small order service returns incorrect totals whenever a cart has more than one unit of an item. Work in this repository to fix the public `total_cents()` behavior. Keep the existing `OrderItem` API, integer-cent calculations, input validation and empty-cart result. Check the visible tests and add a focused check if needed, then run the tests and explain the result.

This is a maintained demonstration project, not a benchmark instance. All tests in the project are visible; there is no hidden solution or scoring script.
