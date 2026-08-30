# When to Mock

Mock at **system boundaries** only:

- External APIs (payment, email, etc.)
- Databases (sometimes - prefer test DB)
- Time/randomness
- File system (sometimes)

Don't mock:

- Your own classes/modules
- Internal collaborators
- Anything you control

## Designing for Mockability

At system boundaries, design interfaces that are easy to mock:

**1. Use dependency injection**

Pass external dependencies in rather than creating them internally:

```typescript
// Easy to mock
function processPayment(order, paymentClient) {
  return paymentClient.charge(order.total);
}

// Hard to mock
function processPayment(order) {
  const client = new StripeClient(process.env.STRIPE_KEY);
  return client.charge(order.total);
}
```

**2. Prefer SDK-style interfaces over generic fetchers**

Create specific functions for each external operation instead of one generic function with conditional logic:

```typescript
// GOOD: Each function is independently mockable
const api = {
  getUser: (id) => fetch(`/users/${id}`),
  getOrders: (userId) => fetch(`/users/${userId}/orders`),
  createOrder: (data) => fetch('/orders', { method: 'POST', body: data }),
};

// BAD: Mocking requires conditional logic inside the mock
const api = {
  fetch: (endpoint, options) => fetch(endpoint, options),
};
```

The SDK approach means:
- Each mock returns one specific shape
- No conditional logic in test setup
- Easier to see which endpoints a test exercises
- Type safety per endpoint

## Typed fakes must type-check

Where the gate type-checks changed test files, a fake must satisfy the
service's annotation. Two working shapes; pick by one rule — can the real
repository be constructed without a database?

- **Subclass the real repository** when constructing it needs no live session:
  `class FakeEventRepository(CalendarRepository)` (see
  tests/unit/test_services.py). The fake is a subtype, so a service annotated
  against the concrete class accepts it.
- **Protocol at the seam** when the real repository needs a session to build:
  the service annotates its dependency with a structural `Protocol`
  (`MealsRepositoryProtocol` in src/nidaro/meals/service.py); the real class
  satisfies it implicitly and the fake stays standalone.

Protocol pitfalls — each missed one costs a full gate cycle:

- The fake must define **every** protocol member, including methods the
  current tests never call; protocol matching is all-members.
- Never give a fake an attribute that shares a name with a protocol method: a
  dict named `dishes` collides with a `dishes()` method and reports as a
  member mismatch, not a naming accident.
- After renaming inside the fake, grep for leftover references to the old
  name before re-running the gate.
