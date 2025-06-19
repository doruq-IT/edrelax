/**
 * 'standart_sezlong' gibi bir string'i 'Standart Sezlong' haline getirir.
 * Bu, .title() fonksiyonunun JavaScript'teki karşılığıdır.
 * @param {string} str - Dönüştürülecek string.
 * @returns {string} - Baş harfleri büyütülmüş string.
 */
function toTitleCase(str) {
    if (!str) return '';
    return str.replace(/_/g, ' ').replace(/\w\S*/g, function(txt) {
        return txt.charAt(0).toUpperCase() + txt.substr(1).toLowerCase();
    });
}

const bedsContainer = document.getElementById("beds-container");
const checkoutBtn = document.getElementById("checkout-btn");
const totalPriceEl = document.getElementById("total-price");
let selectedBedsInfoEl = document.getElementById("selected-beds-info");

const ICONS = {
    'standart_sezlong': 'fa-chair',
    'loca': 'fa-campground',
    'bungalow': 'fa-home',
    'vip_sezlong': 'fa-gem',
    'default': 'fa-umbrella-beach'
};

/**
 * Backend'den gelen itemsByType verisini kullanarak her bir eşyayı
 * HTML olarak oluşturur ve doğru grup konteynerine ekler.
 * Sizin "notify-wrapper" mantığınızı da korur.
 */
function renderItems() {
    // HTML'den `itemsByType` değişkenini okur. Eğer tanımlı değilse veya boşsa işlemi durdurur.
    if (typeof itemsByType === 'undefined' || Object.keys(itemsByType).length === 0) {
        console.warn("Kiralanabilir eşya bulunamadı veya 'itemsByType' değişkeni tanımsız.");
        return;
    }

    // 'loca', 'standart_sezlong' gibi her bir eşya türü için döngüye gir
    for (const type in itemsByType) {
        // O türe ait HTML konteynerini bul (örn: id="container-loca")
        const container = document.getElementById(`container-${type}`);
        if (!container) continue; // Konteyner bulunamazsa bu türü atla

        container.innerHTML = ''; // Yeniden çizimler için konteyneri her ihtimale karşı temizle
        const items = itemsByType[type]; // O türe ait eşyaların listesi

        // Eşya listesindeki her bir 'item' için döngüye gir
        items.forEach(item => {
            const itemDiv = document.createElement("div");
            itemDiv.classList.add("item", item.status); // 'available' veya 'booked' sınıfını ekle

            // Gerekli tüm bilgileri data-* attribute olarak elementin üzerinde sakla
            itemDiv.dataset.itemId = item.id;
            itemDiv.dataset.itemNumber = item.item_number;
            itemDiv.dataset.itemPrice = item.price;
            itemDiv.dataset.itemType = type;

            const iconClass = ICONS[type] || ICONS['default'];

            // Eşyanın temel HTML'ini oluştur
            itemDiv.innerHTML = `
                <i class="fas ${iconClass} item-icon"></i>
                <span class="item-number">No: ${item.item_number}</span>
                <span class="item-price">${item.price.toFixed(2)} TL</span>
            `;

            // EĞER EŞYA DOLUYSA, "Boşalınca Haber Ver" katmanını ekle
            if (item.status === 'booked') {
                itemDiv.title = `Bu eşya dolu. Bildirim için tıklayın.`;
                const notifyWrapper = document.createElement("div");
                notifyWrapper.classList.add("notify-wrapper");
                
                // Gerekli verileri bu yeni katmana ekle
                const date = document.getElementById("selected-date")?.value;
                const start = document.getElementById("selected-start")?.value;
                const end = document.getElementById("selected-end")?.value;
                const reservationWrapper = document.getElementById("reservation-wrapper");

                notifyWrapper.dataset.beachId = reservationWrapper?.dataset.beachId;
                notifyWrapper.dataset.itemId = item.id; // ÖNEMLİ: Artık item_id kullanıyoruz
                notifyWrapper.dataset.date = date;
                notifyWrapper.dataset.timeSlot = `${start}-${end}`;

                notifyWrapper.innerHTML = `
                  <i class="fas fa-bell"></i> 
                  <span class="tooltip-text">Boşalınca<br>Haber Ver</span>
                `;
                itemDiv.appendChild(notifyWrapper);
            } else {
                 itemDiv.title = `${toTitleCase(type)} No: ${item.item_number}`;
            }

            container.appendChild(itemDiv);
        });
    }
}

function updateCheckoutInfo() {
  const selectedItems = document.querySelectorAll(".item.selected");
  let currentTotalPrice = 0;
  let selectedInfoText = [];

  selectedItems.forEach(item => {
    // Her eşyanın kendi fiyatını data-item-price özelliğinden oku ve topla
    currentTotalPrice += parseFloat(item.dataset.itemPrice);
    
    // Bilgi metnini oluştur (örn: "Loca #1", "Standart Sezlong #5")
    const typeName = toTitleCase(item.dataset.itemType);
    selectedInfoText.push(`${typeName} #${item.dataset.itemNumber}`);
  });

  // Toplam fiyatı ve bilgi metnini ekrana yazdır
  totalPriceEl.textContent = currentTotalPrice.toFixed(2);
  selectedInfoEl.textContent = selectedInfoText.length > 0 ? selectedInfoText.join(", ") : "Yok";
}

// 🕒 Geri sayım süresi (saniye cinsinden)
let countdown = 180;
const countdownEl = document.getElementById("countdown-timer");

function formatTime(sec) {
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

// 🔁 Her saniye güncelle
const countdownInterval = setInterval(() => {
  countdown--;
  if (countdownEl) countdownEl.textContent = formatTime(countdown);

  if (countdown <= 0) {
    clearInterval(countdownInterval);
    Swal.fire({
      icon: "info",
      title: "Süre Doldu",
      text: "Seçim süreniz sona erdi. Sayfa yeniden yüklenecek.",
      timer: 4000,
      showConfirmButton: false
    }).then(() => {
      location.reload();
    });
  }
}, 1000);

// 🚀 Check Out ve Rezervasyon Kaydı
checkoutBtn.addEventListener("click", () => {
  // Seçili eşyaları al
  const selectedItems = document.querySelectorAll(".item.selected");
  if (selectedItems.length === 0) {
    Swal.fire({
      icon: "warning",
      title: "Seçim yapılmadı",
      text: "Lütfen en az bir eşya seçin."
    });
    return;
  }

  // Limit kontrolü
  if ((previouslyReservedCount + selectedItems.length) > DAILY_MAX_ITEMS) {
    Swal.fire({
      icon: "error",
      title: "Limit Aşıldı!",
      text: `Günlük maksimum eşya limitini (${DAILY_MAX_ITEMS}) aştınız.`,
      confirmButtonText: "Anladım"
    });
    return;
  }
  
  // Gerekli verileri al
  const date = document.getElementById("selected-date")?.value;
  const start = document.getElementById("selected-start")?.value;
  const end = document.getElementById("selected-end")?.value;
  const reservationWrapper = document.getElementById("reservation-wrapper");
  const beachId = reservationWrapper?.dataset.beachId;

  if (!date || !start || !end || !beachId) {
    Swal.fire({ icon: "error", title: "Eksik bilgi", text: "Rezervasyon verileri eksik."});
    return;
  }
  
  checkoutBtn.disabled = true;
  checkoutBtn.innerText = "Gönderiliyor...";
  clearInterval(countdownInterval);

  // Sunucuya gönderilecek payload'ı hazırla
  const itemIds = Array.from(selectedItems).map(item => parseInt(item.dataset.itemId));

  const payload = {
    beach_id: parseInt(beachId),
    item_ids: itemIds,
    date: date,
    start_time: start,
    end_time: end
  };
  
  const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

  // fetch isteği BURADA, addEventListener'ın İÇİNDE yapılmalı
  fetch("/make-reservation", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken
    },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        // Başarı mesajını sadeleştiriyoruz
        Swal.fire({
          icon: "success",
          title: "Rezervasyon Tamamlandı!",
          text: "Ödemeyi plajda yapabilirsiniz. Detayları 'Rezervasyonlarım' sayfasından görebilirsiniz.",
          confirmButtonText: "Harika!"
        }).then(() => {
          // Sayfayı önbelleğe takılmadan yenile
          const currentUrl = new URL(window.location.href);
          currentUrl.searchParams.set('_v', new Date().getTime());
          window.location.href = currentUrl.toString();
        });
      } else {
        // Hata durumunda butonu tekrar aktif et
        Swal.fire({
          icon: "error",
          title: "Hata",
          text: data.message || "Rezervasyon oluşturulamadı."
        });
        checkoutBtn.disabled = false;
        checkoutBtn.innerText = "Ödemeye Geç";
      }
    })
    .catch(err => {
      console.error("Fetch Hatası:", err);
      Swal.fire({
        icon: "error",
        title: "Sunucu hatası",
        text: "Bir hata oluştu. Lütfen tekrar deneyin."
      });
      checkoutBtn.disabled = false;
      checkoutBtn.innerText = "Ödemeye Geç";
    });
}); // checkoutBtn.addEventListener fonksiyonunun kapanış parantezi

let currentlyTouchedItem = null; // DEĞİŞİKLİK: Değişken adı daha genel hale getirildi.

// Tüm tıklama olaylarını merkezi olarak yöneten ana fonksiyon
document.body.addEventListener("click", async (event) => {
  const clickedElement = event.target;

  // 1. "Boşalınca Haber Ver" katmanına mı tıklandı?
  const notifyWrapper = clickedElement.closest(".notify-wrapper");
  if (notifyWrapper) {
    event.stopPropagation(); // Diğer tıklama olaylarını engelle
    if (currentlyTouchedItem) {
      currentlyTouchedItem.classList.remove("is-touched");
      currentlyTouchedItem = null;
    }
    await handleNotifyRequest(notifyWrapper); // Yardımcı fonksiyonu çağır
    return;
  }

  // Tıklanan yerin bir eşya (.item) olup olmadığını bul
  const clickedItem = clickedElement.closest(".item");

  // Eğer bir eşyaya tıklanmadıysa, dokunulmuş olanı kapat ve işlemi bitir.
  if (!clickedItem) {
    if (currentlyTouchedItem) {
      currentlyTouchedItem.classList.remove("is-touched");
      currentlyTouchedItem = null;
    }
    return;
  }

  // 2. Dolu bir eşyaya mı tıklandı? (Mobil için dokunma mantığı)
  if (clickedItem.classList.contains("booked")) {
    if (currentlyTouchedItem && currentlyTouchedItem !== clickedItem) {
      currentlyTouchedItem.classList.remove("is-touched");
    }
    clickedItem.classList.toggle("is-touched");
    currentlyTouchedItem = clickedItem.classList.contains("is-touched") ? clickedItem : null;
  }
  
  // 3. Boş bir eşyaya mı tıklandı?
  if (clickedItem.classList.contains("available")) {
    if (currentlyTouchedItem) {
      currentlyTouchedItem.classList.remove("is-touched");
      currentlyTouchedItem = null;
    }
    handleItemSelection(clickedItem); // Yardımcı fonksiyonu çağır
  }
});


// === YARDIMCI FONKSİYONLAR ===

// Boş eşya seçme mantığını yöneten fonksiyon
function handleItemSelection(itemElement) {
  const suAnSeciliOlanlarUI = document.querySelectorAll(".item.selected").length;
  const buEşyaSeciliMi = itemElement.classList.contains("selected");

  // DEĞİŞİKLİK: Limit kontrolü artık DAILY_MAX_ITEMS kullanıyor
  if (!buEşyaSeciliMi && (previouslyReservedCount + suAnSeciliOlanlarUI >= DAILY_MAX_ITEMS)) {
    Swal.fire({
      icon: "warning",
      title: "Limit Aşıldı",
      text: `Bir günde en fazla ${DAILY_MAX_ITEMS} adet eşya seçebilirsiniz.`,
    });
    return;
  }
  itemElement.classList.toggle("selected");
  updateCheckoutInfo(); // DEĞİŞİKLİK: Yeni fiyat güncelleme fonksiyonunu çağır
}

// "Boşalınca Haber Ver" isteğini yöneten fonksiyon
async function handleNotifyRequest(notifyWrapper) {
  // DEĞİŞİKLİK: Artık 'bedNumber' yerine 'itemId' kullanıyoruz
  const beachId = notifyWrapper.dataset.beachId;
  const itemId = notifyWrapper.dataset.itemId;
  const date = notifyWrapper.dataset.date;
  const timeSlot = notifyWrapper.dataset.timeSlot;

  if (!beachId || !itemId || !date || !timeSlot) {
    Swal.fire("Hata", "Eşya bilgisi eksik.", "error");
    return;
  }

  const confirm = await Swal.fire({
    title: "Bu eşya dolu!",
    text: "Boşalınca size haber verelim mi?",
    icon: "info",
    showCancelButton: true,
    confirmButtonText: "Evet, haber ver",
    cancelButtonText: "Hayır",
  });

  if (!confirm.isConfirmed) return;

  try {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    const res = await fetch("/notify-when-free", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(csrfToken && { "X-CSRFToken": csrfToken }) },
      // DEĞİŞİKLİK: Backend'e artık 'bed_number' yerine 'item_id' gönderiyoruz
      body: JSON.stringify({ beach_id: beachId, item_id: itemId, date: date, time_slot: timeSlot }),
    });
    const result = await res.json();
    if (res.ok) {
      Swal.fire("Tamamdır!", result.message || "Bildirim kaydınız alındı.", "success");
    } else {
      Swal.fire("Hata", result.message || "Bir hata oluştu", "error");
    }
  } catch (error) {
    Swal.fire("Sunucu Hatası", "Sunucuya ulaşılamadı.", "error");
  }
}
renderItems();