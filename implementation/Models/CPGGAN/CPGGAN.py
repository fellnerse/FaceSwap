from torch.distributions import MultivariateNormal

from Configuration.config_general import ARRAY_LANDMARKS_28_MEAN, ARRAY_LANDMARKS_28_COV, \
    ARRAY_LOWRES_4_MEAN, ARRAY_LOWRES_4_COV
from Models.ModelUtils.ModelUtils import norm_img
from Models.PGGAN.PGGAN import PGGAN
from Models.PGGAN.model import torch, np
from Preprocessor.FaceExtractor import extract_landmarks, extract_lowres


class CPGGAN(PGGAN):
    """
    This model is a combination of PGGAN (Progressive GAN) and CGAN (Conditional GAN)
    """

    def __init__(self, **kwargs):
        super(CPGGAN, self).__init__(**kwargs)
        if self.mode == 'train':
            # path to numpy arrays containing the calculated mean and cov matrices for calculating a multivariate gaussian
            path_to_lm_mean = kwargs.get('lm_mean', ARRAY_LANDMARKS_28_MEAN)
            path_to_lm_cov = kwargs.get('lm_cov', ARRAY_LANDMARKS_28_COV)
            path_to_lr_mean = kwargs.get('lr_mean', ARRAY_LOWRES_4_MEAN)
            path_to_lr_cov = kwargs.get('lr_cov', ARRAY_LOWRES_4_COV)

            # ==================================================
            # Currently only preparation for extensions
            # ==================================================
            # gaussian distribution of our landmarks
            self.landmarks_mean = np.load(path_to_lm_mean)
            self.landmarks_cov = np.load(path_to_lm_cov)
            self.landmarks_mean = torch.from_numpy(self.landmarks_mean)
            self.landmarks_cov = torch.from_numpy(self.landmarks_cov)
            self.distribution_landmarks = MultivariateNormal(loc=self.landmarks_mean.type(torch.float64),
                                                             covariance_matrix=self.landmarks_cov.type(torch.float64))
            # gaussian distribution of our low res pixel map
            self.lowres_mean = np.load(path_to_lr_mean)
            self.lowres_cov = np.load(path_to_lr_cov)
            self.lowres_mean = torch.from_numpy(self.lowres_mean)
            self.lowres_cov = torch.from_numpy(self.lowres_cov)
            self.distribution_lowres = MultivariateNormal(loc=self.lowres_mean.type(torch.float64),
                                                          covariance_matrix=self.lowres_cov.type(torch.float64))
            # static noise for calculating the validation
            self.static_landmarks = 2 * (
                    self.distribution_landmarks.sample((self.batch_size,)).type(torch.float32) - 0.5)
            self.static_lowres = 2 * (self.distribution_lowres.sample((self.batch_size,)).type(torch.float32) - 0.5)

        # Static noise for anonymization
        self.anonymization_noise = self.noise(1)

    def train(self, train_data_loader, batch_size, validate, **kwargs):

        if not validate:
            self.schedule_resolution()
            train_data_loader = self.data_loader.get_train_data_loader()

        # sum the loss for logging
        g_loss_summed, d_loss_summed, wasserstein_d_summed, eps_summed = 0, 0, 0, 0
        iterations = 0

        for images, features in train_data_loader:
            # set the fade_in_factor:
            # during stabilizing phase we don't interpolate but use the current level=resolution
            # after increasing the resolution we interpolate between de lower and higher resolution
            # i.e.: self.level = 3 (4*1*2*2x4*1*2*2: 16x16)
            # this means we were in level 2 but interpolate to level 3:
            # cur_level = self.level - 1 = 2
            # now we add the fade_in_factor which is between 1e-10 and 1
            # as a result the cur_level is a value between the last level and the current value, but it has to be
            # greater then the last level (2) otherwise the forward does not work

            if self.stabilization_phase:
                fade_in_factor = 0
                cur_level = self.resolution_level
            else:
                fade_in_factor = self.images_faded_in / self.images_per_fading_phase
                cur_level = self.resolution_level - 1 + (
                    fade_in_factor if fade_in_factor != 0 else 1e-10)  # FuckUp implementation...

            # differentiate between validation and training
            if validate:
                noise = self.static_noise[:self.batch_size]
                features = torch.cat([self.static_landmarks[:self.batch_size], self.static_lowres[:self.batch_size]], 1)
            else:
                noise = self.noise(self.batch_size)

            # Move to GPU
            if self.cuda:
                images = images.cuda()
                noise = noise.cuda()
                features = features.cuda()

            # because of the conditioning we concatenate noise and features to one big vector
            input_vec = torch.cat([noise, features], 1)
            # for the discriminator the process is a bit more complicated:
            # we add the features as additional channels to the input image
            features_fill = features.view((self.batch_size, -1, 1, 1)).repeat((1, 1, images.shape[2], images.shape[2]))
            input_img_real = torch.cat([images, features_fill], 1)
            ############################
            # (1) Update D network: minimize -D(x) + D(G(z)) + penalty instead of clipping
            ###########################
            if not validate:
                # Avoid computations in Generator training
                self.D.train(True)
                self.D_optimizer.zero_grad()

            # Train on real example with real features
            D_real = self.D(input_img_real, cur_level=cur_level)

            # Epsilon loss => 4th loss term from Nvidia paper
            eps_loss = D_real ** 2
            eps_loss = 0.001 * eps_loss.mean()

            # Wasserstein Loss
            D_real = -D_real.mean() + eps_loss
            if not validate:
                D_real.backward()

            # Train on fake example from generator
            G_fake = self.G(input_vec, cur_level=cur_level)
            if validate:
                # Validate only generated image
                break

            # concat the input so that the discriminator gets the conditional data as well
            input_img_fake = torch.cat([G_fake, features_fill], 1)
            D_fake = self.D(input_img_fake.detach(), cur_level=cur_level)

            # Wasserstein Loss
            D_fake = D_fake.mean()
            if not validate:
                D_fake.backward()

            # Wasserstein loss
            # train with gradient penalty
            gp = self.calculate_gradient_penalty(input_img_real, input_img_fake.detach(), cur_level)
            if not validate:
                gp.backward()

            # Wasserstein loss
            D_loss = float(D_fake - D_real + gp)
            Wasserstein_D = float(D_real - D_fake)

            if not validate:
                self.D_optimizer.step()

            ############################
            # (2) Update G network: minimize -D(G(z)) (is same to maximise D(G(z)) / Discriminator makes an error)
            ###########################
            if not validate:
                self.D.train(False)
                self.G_optimizer.zero_grad()

            # Train on fooling the Discriminator
            D_fake = self.D(input_img_fake, cur_level=cur_level)

            # Wasserstein Loss
            D_fake = -D_fake.mean()
            if not validate:
                D_fake.backward()
                self.G_optimizer.step()
            G_loss = float(D_fake)

            # losses
            g_loss_summed += G_loss
            d_loss_summed += D_loss
            wasserstein_d_summed += Wasserstein_D
            eps_summed += float(eps_loss)
            iterations += 1

            if not self.stabilization_phase and not validate:
                # Count only images during training
                self.images_faded_in += self.batch_size

        if not validate:
            g_loss_summed /= iterations
            d_loss_summed /= iterations
            log_info = {'loss': {'lossG': g_loss_summed,
                                 'lossD': d_loss_summed},
                        'info/WassersteinDistance': wasserstein_d_summed,
                        'info/eps': eps_summed,
                        'info/curr_level': cur_level}
            log_img = G_fake
        else:
            log_info = {}
            log_img = G_fake

        return log_info, log_img

    def anonymize(self, extracted_face, extracted_information, level_out=None):
        """
        :param extracted_face:
        :param extracted_information:
        level_out: Output layer
        :return:
        """
        # ===== Landmarks
        # Normalize landmarks
        landmarks = np.array(extracted_information.landmarks) / extracted_information.size_fine
        landmarks = landmarks.reshape(-1)
        # Extract needed landmarks
        landmarks = extract_landmarks(landmarks, n=10)  # adjust number of landmarks
        landmarks = torch.from_numpy(landmarks).type(torch.float32)

        # ===== LowRes
        lowres = extract_lowres(extracted_face, resolution=2)  # adjust low resolution
        lowres = torch.from_numpy(lowres).type(torch.float32)

        # ===== Creating feature vector
        feature = torch.cat([landmarks, lowres], 1)  # use landmarks & lowres
        # feature = landmarks  # use only landmarks
        # ===== Zero centering
        feature -= 0.5
        feature *= 2.0

        # ===== Create input vector & move to GPU
        input_vec = torch.cat([self.noise(1), feature], 1)
        if self.cuda:
            input_vec = input_vec.cuda()

        # ===== Determine output resolution
        if level_out is None:
            level = int(np.log2(self.target_resolution)) - 1
        else:
            level = level_out
        # ===== Generate image
        # Default: Generate image on highest resolution
        # If images on a lower level should be generated, set the level manually
        tensor_img = self.G(input_vec, cur_level=level)

        # ===== Denormalize generated image
        for t in tensor_img:  # loop over mini-batch dimension
            norm_img(t)
        tensor_img *= 255
        tensor_img = tensor_img.type(torch.uint8)
        return tensor_img
