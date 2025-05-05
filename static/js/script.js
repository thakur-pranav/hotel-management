
// Ensure DOM is fully loaded before executing
document.addEventListener('DOMContentLoaded', function() {
    // Select payment method and card details elements
    const paymentMethod = document.querySelector('#payment_method');
    const cardDetails = document.querySelector('#card_details');

    // Check if elements exist before adding event listener
    if (paymentMethod && cardDetails) {
        paymentMethod.addEventListener('change', function() {
            // Toggle card details visibility based on payment method
            cardDetails.style.display = this.value === 'PayPal' ? 'none' : 'block';
        });
    }
});
