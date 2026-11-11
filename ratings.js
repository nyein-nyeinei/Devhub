document.addEventListener("DOMContentLoaded", () => {
    // Helper function: သတ်မှတ်ထားသော Rating အထိ ကြယ်များကို Highlight ပြပေးမည်
    const highlightStars = (container, ratingCount) => {
        const stars = container.querySelectorAll(".rating-star");
        stars.forEach(s => {
            if (Number(s.dataset.rating) <= Number(ratingCount)) {
                s.classList.remove("grayscale", "opacity-40");
            } else {
                s.classList.add("grayscale", "opacity-40");
            }
        });
    };

    // Page စတင် Load ချိန် သို့မဟုတ် AJAX ဖြင့် ရောက်လာသော Cards များအတွက် Initial Highlight သတ်မှတ်ခြင်း
    const initRatings = () => {
        document.querySelectorAll(".rating-container").forEach(container => {
            const initialRating = container.dataset.selectedRating || 0;
            highlightStars(container, initialRating);
        });
    };

    initRatings();

    // 1. Mouse Enter Event Delegation (Hover Highlight ပြရန်)
    document.addEventListener("mouseover", (e) => {
        const star = e.target.closest(".rating-star");
        if (star) {
            const container = star.closest(".rating-container");
            if (container) {
                highlightStars(container, star.dataset.rating);
            }
        }
    });

    // 2. Mouse Leave Event Delegation (Hover ဖယ်လိုက်လျှင် မူလ Rating သို့ ပြန်သွားရန်)
    document.addEventListener("mouseout", (e) => {
        const container = e.target.closest(".rating-container");
        if (container && !container.contains(e.relatedTarget)) {
            const savedRating = container.dataset.selectedRating || 0;
            highlightStars(container, savedRating);
        }
    });

    // 3. Click Event Delegation (Rating ပို့ရန်)
    document.addEventListener("click", (e) => {
        const star = e.target.closest(".rating-star");
        if (!star) return;

        const container = star.closest(".rating-container");
        if (!container) return;

        const rating = star.dataset.rating;
        const resourceId = container.dataset.resourceId;

        fetch("/rate-resource", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                resource_id: resourceId,
                rating: Number(rating)
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === "success") {
                const card = container.closest(".resource-card");
                if (card) {
                    const avgRating = card.querySelector(".avg-rating");
                    const totalVoters = card.querySelector(".total-voters");

                    if (avgRating) avgRating.textContent = data.avg_rating;
                    if (totalVoters) totalVoters.textContent = data.total_voters;
                }

                // ရွေးချယ်လိုက်သော Rating ကို Container တွင် မှတ်ထားမည်
                container.dataset.selectedRating = rating;

                // ပေးလိုက်သော Rating အတိုင်း အဝါရောင် လင်းကျန်ခဲ့စေမည်
                highlightStars(container, rating);

                // SweetAlert2 Toast ပြသမည်
                Swal.fire({
                    icon: 'success',
                    title: data.message || 'Rating ပေးပြီးပါပြီ',
                    toast: true,
                    position: 'top-end',
                    showConfirmButton: false,
                    timer: 2500,
                    timerProgressBar: true
                });
            } else {
                Swal.fire({
                    icon: 'error',
                    title: 'မအောင်မြင်ပါ',
                    text: data.message || "Rating ပေး၍ မရပါ၊ ပြန်လည် ကြိုးစားပါ။",
                    customClass: { popup: 'rounded-2xl' }
                });
            }
        })
        .catch(error => {
            console.error("Rating Error:", error);
            Swal.fire({
                icon: 'error',
                title: 'Error ဖြစ်သွားပါသည်',
                text: "Rating ပေးရာတွင် အမှားတစ်ခု ဖြစ်ပေါ်နေပါသည်။",
                customClass: { popup: 'rounded-2xl' }
            });
        });
    });
});